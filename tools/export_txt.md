# export_txt.py — 电子书纯文本导出工具

从 Reader3 的 `book.pkl` 数据文件中提取全书文本，导出为 `.txt` 纯文本文件。

## 用法

```bash
python tools/export_txt.py <pkl文件路径>
```

## 示例

```bash
# 导出单本书
python tools/export_txt.py books/dracula_data/book.pkl

# 输出文件自动保存为同目录下的 book.txt
# → books/dracula_data/book.txt
```

## 工作原理

1. 加载 `book.pkl`（Reader3 解析 EPUB 后的 pickle 数据）
2. 递归遍历 `book.spine` 中的所有章节对象
3. 按优先级提取 `content` / `text` / `paragraphs` 等文本属性
4. 拼接所有章节文本，写入 `.txt` 文件

## 适用场景

- 将电子书内容导出给 AI 做长文分析
- 备份书籍的纯文本内容
- 全文搜索或文本处理
