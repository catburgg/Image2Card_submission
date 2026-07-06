"""
demo.py — PP-OCRv5 Word Detection & Recognition Demo
------------------------------------------------------
Usage:
    python demo.py --image path/to/image.jpg
    python demo.py --image path/to/image.jpg --device gpu:0
    python demo.py --image path/to/image.jpg --device cpu --save_dir ./out

Output:
    • Console: each detected word with index / confidence / bbox
    • File   : <save_dir>/vis_<original_name>.jpg  (image with drawn polygons)
"""

import argparse
import os
import sys
import textwrap
from pathlib import Path

import cv2
import numpy as np
from paddleocr import PaddleOCR


# ── colour palette (BGR) ────────────────────────────────────────────────────
PALETTE = [
    (0, 200, 255),   # amber
    (50, 220, 50),   # green
    (255, 100, 50),  # blue-ish
    (180, 60, 255),  # purple
    (0, 180, 220),   # orange
]


# ── helpers ─────────────────────────────────────────────────────────────────

def poly_to_rect(poly: np.ndarray):
    """4-point polygon → axis-aligned (x_min, y_min, x_max, y_max)."""
    xs, ys = poly[:, 0], poly[:, 1]
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def draw_results(image_bgr: np.ndarray,
                 polys: np.ndarray,
                 texts: list[str],
                 scores: list[float]) -> np.ndarray:
    """
    Draw filled semi-transparent polygon + thin outline + index label on image.
    Returns a copy; does NOT modify the original.
    """
    vis = image_bgr.copy()
    overlay = image_bgr.copy()

    for idx, (poly, text, score) in enumerate(zip(polys, texts, scores)):
        pts = poly.astype(np.int32).reshape((-1, 1, 2))
        color = PALETTE[idx % len(PALETTE)]

        # Semi-transparent fill
        cv2.fillPoly(overlay, [pts], color)

        # Blend overlay onto vis (alpha = 0.25)
        cv2.addWeighted(overlay, 0.25, vis, 0.75, 0, vis)
        overlay = vis.copy()          # reset overlay for next box

        # Solid outline
        cv2.polylines(vis, [pts], isClosed=True, color=color, thickness=2,
                      lineType=cv2.LINE_AA)

        # Index label at top-left corner of polygon
        x_min, y_min, _, _ = poly_to_rect(poly)
        label = f"#{idx+1}"
        label_pos = (max(x_min, 2), max(y_min - 6, 12))
        (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX,
                                             0.45, 1)
        cv2.rectangle(vis,
                      (label_pos[0] - 2, label_pos[1] - th - 2),
                      (label_pos[0] + tw + 2, label_pos[1] + baseline),
                      color, -1)
        cv2.putText(vis, label, label_pos,
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (10, 10, 10),
                    1, cv2.LINE_AA)

    return vis


def print_results(texts: list[str],
                  scores: list[float],
                  polys: np.ndarray,
                  image_path: str):
    """Pretty-print detection results to stdout."""
    sep = "─" * 68
    print(f"\n{sep}")
    print(f"  Image : {image_path}")
    print(f"  Words : {len(texts)}")
    print(sep)
    print(f"  {'#':>4}  {'Conf':>6}  {'BBox (x0,y0,x1,y1)':^22}  Word")
    print(sep)
    for idx, (text, score, poly) in enumerate(zip(texts, scores, polys), 1):
        x0, y0, x1, y1 = poly_to_rect(poly)
        bbox_str = f"({x0},{y0},{x1},{y1})"
        # Truncate long words for display
        display = text
        print(f"  {idx:>4}  {score:>6.4f}  {bbox_str:^22}  {display}")
    print(sep)
    print()
def dump_results(texts, scores, polys, save_path):
    """Save OCR results to a text file."""
    with open(save_path, "w", encoding="utf-8") as f:
        for idx, (text, score, poly) in enumerate(zip(texts, scores, polys), 1):
            x0, y0, x1, y1 = poly_to_rect(poly)
            bbox_str = f"({x0},{y0},{x1},{y1})"
            f.write(f"{idx}\t{score:.4f}\t{bbox_str}\t{text}\n")
    print(f"[INFO] OCR results saved → {save_path}")

# ── main ────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="PP-OCRv5 demo — draws word bboxes and prints recognised text",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python demo.py --image doc.jpg
              python demo.py --image doc.jpg --device gpu:0
              python demo.py --image doc.jpg --device cpu --save_dir ./results
        """),
    )
    p.add_argument("--image", required=True,
                   help="Path to input image (jpg / png / bmp / tiff)")
    p.add_argument("--device", default="cpu",
                   help="Inference device: 'cpu' | 'gpu:0' | 'gpu:1' … (default: cpu)")
    p.add_argument("--save_dir", default="./output",
                   help="Directory to save visualised image (default: ./output)")
    p.add_argument("--det_model", default="PP-OCRv5_server_det",
                   help="Detection model name (default: PP-OCRv5_server_det)")
    p.add_argument("--rec_model", default="PP-OCRv5_server_rec",
                   help="Recognition model name (default: PP-OCRv5_server_rec)")
    p.add_argument("--no_rec", action="store_true",
                   help="Run detection only (no text recognition)")
    return p.parse_args()


def main():
    args = parse_args()

    # ── validate input ───────────────────────────────────────────────────────
    if not os.path.isfile(args.image):
        sys.exit(f"[ERROR] Image not found: {args.image}")

    os.makedirs(args.save_dir, exist_ok=True)

    # ── load image ───────────────────────────────────────────────────────────
    image_bgr = cv2.imread(args.image)
    if image_bgr is None:
        sys.exit(f"[ERROR] cv2.imread failed for: {args.image}")
    h, w = image_bgr.shape[:2]
    print(f"[INFO] Image loaded — {w}×{h}px  |  device={args.device}")

    # ── build model ──────────────────────────────────────────────────────────
    print(f"[INFO] Loading PP-OCRv5 …  det={args.det_model}  "
          f"rec={'disabled' if args.no_rec else args.rec_model}")

    ocr = PaddleOCR(
        text_detection_model_name=args.det_model,
        text_recognition_model_name=args.rec_model,
        use_doc_orientation_classify=False,   # keep pipeline lean for demo
        use_doc_unwarping=False,
        use_textline_orientation=True,        # handles upside-down lines
        device=args.device,
    )

    # ── inference ────────────────────────────────────────────────────────────
    print("[INFO] Running inference …")
    results = ocr.predict(args.image)

    # ── parse result ─────────────────────────────────────────────────────────
    # PaddleOCR v3 pipeline returns a list (one entry per image).
    # Each entry is a dict-like object; access via res[key] or res.
    res = results[0]              # single image

    if args.no_rec:
        # Detection-only branch
        polys  = np.array(res["dt_polys"],  dtype=np.int32)   # (N,4,2)
        scores = list(res["dt_scores"])
        texts  = [f"det_{i}" for i in range(len(scores))]
    else:
        # Full OCR branch — use rec_polys which are aligned with rec_texts
        polys  = np.array(res["rec_polys"],  dtype=np.int32)  # (N,4,2)
        texts  = list(res["rec_texts"])
        scores = list(res["rec_scores"])

    if len(polys) == 0:
        print("[WARN] No text detected in this image.")
        sys.exit(0)

    # ── print to console ──────────────────────────────────────────────────────
    print_results(texts, scores, polys, args.image)

    # ── draw & save ───────────────────────────────────────────────────────────
    vis = draw_results(image_bgr, polys, texts, scores)
    stem = Path(args.image).stem
    out_path = os.path.join(args.save_dir, f"vis_{stem}.jpg")
    dump_results(texts, scores, polys, os.path.join(args.save_dir, f"ocr_results_{stem}.txt"))

    cv2.imwrite(out_path, vis, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(f"[INFO] Visualisation saved → {out_path}")


if __name__ == "__main__":
    main()

