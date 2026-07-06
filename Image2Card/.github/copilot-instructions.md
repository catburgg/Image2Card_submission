语言: python,
Tkinter、PyQt、Kivy等，不限定用于搭建界面的库，但不能使用网页界面(即搭建一个web demo)•使用Python 面向对象的方法完成本次项目•鼓励写注释提高代码可读性和可维护性


```json
{
  "scene_type": "restaurant_menu",
  "language": "Italian",
  "summary": "A restaurant menu containing several Italian pasta and dessert items.",
  "items": [
    {
      "original_text": "Spaghetti Carbonara",
      "card": "Carbonara",
      "card_id": 1, // can be null if the card is not created yet
      "status": "new" | "existing"
      "bbox": {
        "x1": 120,
        "y1": 240,
        "x2": 300,
        "y2": 272
      },
    },
  ],
  "cards": [
    {
      "card": "Carbonara",
      "card summary": "A classic Italian pasta dish made with eggs, cheese, pancetta, and pepper.",
      "model content": "Spaghetti Carbonara is a traditional Italian dish that originated in Rome. It is made with spaghetti pasta, eggs, Pecorino Romano cheese, guanciale (cured pork cheek), and black pepper. The dish is known for its creamy texture and rich flavor, achieved by mixing the hot pasta with the raw egg mixture, which cooks the eggs and creates a silky sauce.",
      "familiarity_suggestion": 1,
      "term_type": "dish",
      "links": [
        {
          "title": "Wikipedia",
          "url": "https://en.wikipedia.org/wiki/Carbonara"
        }
      ],
      "bbox": {
        "x1": 120,
        "y1": 240,
        "x2": 300,
        "y2": 272 
      },
      "related_terms": ["Guanciale", "Pecorino Romano"]
    }
  ]
}
```


log使用logging 