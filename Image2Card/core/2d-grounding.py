import json
import ast
import os
import requests

from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from PIL import ImageColor
from openai import OpenAI


additional_colors = [colorname for (colorname, colorcode) in ImageColor.colormap.items()]

def decode_json_points(text: str):
    """Parse coordinate points from text format"""
    try:
        # 清理markdown标记
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]

        # 解析JSON
        data = json.loads(text)
        points = []
        labels = []

        for item in data:
            if "point_2d" in item:
                x, y = item["point_2d"]
                points.append([x, y])

                # 获取label，如果没有则使用默认值
                label = item.get("label", f"point_{len(points)}")
                labels.append(label)

        return points, labels

    except Exception as e:
        print(f"Error: {e}")
        return [], []


def plot_bounding_boxes(img_path, bounding_boxes):

    """
        在图像上绘制边界框，并标注名称
    Args:
        img_path: 图像的路径
        bounding_boxes: 包含对象名称的边界框列表，并且位置为标准化的[y1 x1 y2 x2]格式。
    """

    # 加载图像并创建绘图对象
    img = img_path
    width, height = img.size
    print(img.size)

    draw = ImageDraw.Draw(img)

    # 定义颜色列表用于区分不同对象
    colors = [
                 'red',
                 'green',
                 'blue',
                 'yellow',
                 'orange',
                 'pink',
                 'purple',
                 'brown',
                 'gray',
                 'beige',
                 'turquoise',
                 'cyan',
                 'magenta',
                 'lime',
                 'navy',
                 'maroon',
                 'teal',
                 'olive',
                 'coral',
                 'lavender',
                 'violet',
                 'gold',
                 'silver',
             ] + additional_colors

    # 解析边界框信息
    bounding_boxes = parse_json(bounding_boxes)

    font = ImageFont.truetype("msyh.ttc", 24) 
    try:
        json_output = ast.literal_eval(bounding_boxes)
    except Exception as e:
        end_idx = bounding_boxes.rfind('"}') + len('"}')
        truncated_text = bounding_boxes[:end_idx] + "]"
        json_output = ast.literal_eval(truncated_text)

    if not isinstance(json_output, list):
        json_output = [json_output]

    # 绘制每个边界框
    for i, bounding_box in enumerate(json_output):
        color = colors[i % len(colors)]

        # 将标准化坐标映射到原图上，变为绝对坐标
        abs_y1 = int(bounding_box["bbox_2d"][1] / 1000 * height)
        abs_x1 = int(bounding_box["bbox_2d"][0] / 1000 * width)
        abs_y2 = int(bounding_box["bbox_2d"][3] / 1000 * height)
        abs_x2 = int(bounding_box["bbox_2d"][2] / 1000 * width)

        if abs_x1 > abs_x2:
            abs_x1, abs_x2 = abs_x2, abs_x1

        if abs_y1 > abs_y2:
            abs_y1, abs_y2 = abs_y2, abs_y1

        # 绘制矩形框
        draw.rectangle(
            ((abs_x1, abs_y1), (abs_x2, abs_y2)), outline=color, width=3
        )

        # 添加标签文字
        if "label" in bounding_box:
            draw.text((abs_x1 + 8, abs_y1 + 6), bounding_box["label"], fill=color, font=font)

    # 显示最终图像
    img.show()


def plot_points(im, text):
    img = im
    width, height = img.size
    draw = ImageDraw.Draw(img)
    colors = [
                 'red', 'green', 'blue', 'yellow', 'orange', 'pink', 'purple', 'brown', 'gray',
                 'beige', 'turquoise', 'cyan', 'magenta', 'lime', 'navy', 'maroon', 'teal',
                 'olive', 'coral', 'lavender', 'violet', 'gold', 'silver',
             ] + additional_colors

    points, descriptions = decode_json_points(text)
    print("Parsed points: ", points)
    print("Parsed descriptions: ", descriptions)
    if points is None or len(points) == 0:
        img.show()
        return

    font = ImageFont.truetype("msyh.ttc", 24)

    for i, point in enumerate(points):
        color = colors[i % len(colors)]
        abs_x1 = int(point[0]) / 1000 * width
        abs_y1 = int(point[1]) / 1000 * height
        radius = 2
        draw.ellipse([(abs_x1 - radius, abs_y1 - radius), (abs_x1 + radius, abs_y1 + radius)], fill=color)
        draw.text((abs_x1 - 20, abs_y1 + 6), descriptions[i], fill=color, font=font)

    img.show()



# 解析JSON输出
def parse_json(json_output):
    # 移除Markdown代码块标记
    lines = json_output.splitlines()
    for i, line in enumerate(lines):
        if line == "```json":
            json_output = "\n".join(lines[i + 1:])  # 删除 "```json"之前的所有内容
            json_output = json_output.split("```")[0]  # 删除 "```"之后的所有内容
            break  # 找到"```json"后退出循环
    return json_output



# 调用Qwen3-VL的 API
def inference_with_api(prompt, sys_prompt="You are a helpful assistant.", model_id="qwen3-vl-plus",
                       min_pixels=4 * 32 * 32, max_pixels=2560 * 32 * 32):
    client = OpenAI(
        # 若没有配置环境变量，请用阿里云百炼API Key将下行替换为：api_key="sk-xxx",
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    messages = [
        {
            "role": "system",
            "content": [{"type": "text", "text": sys_prompt}]},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "min_pixels": min_pixels,
                    "max_pixels": max_pixels,
                    "image_url": {"url": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251031/dhsvgy/img_2.png"},
                },
                {"type": "text", "text": prompt},
            ],
        }
    ]
    completion = client.chat.completions.create(
        model=model_id,
        messages=messages,

    )
    return completion.choices[0].message.content



def run_object_detection(img_url,model_response):
    # 从URL下载图像
    response = requests.get(img_url)
    response.raise_for_status()
    image = Image.open(BytesIO(response.content))
    # 调用函数绘制边界框
    plot_bounding_boxes(image, model_response)


if __name__ == "__main__":
    url = "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251031/dhsvgy/img_2.png"
    prompt = """识别图片中的所有食物，并以JSON格式输出其bbox的坐标及其中文名称"""

    response = inference_with_api(url,  prompt,min_pixels=64 * 32 * 32, max_pixels=2560 * 32 * 32)
    print(response)
    # 调用run_object_detection函数，传入图像URL和模型响应数据
    run_object_detection(url, response)



