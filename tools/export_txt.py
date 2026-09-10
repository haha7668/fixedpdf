import os
import pickle
import sys
import traceback


# === 空壳类名单 (保持不动，防止报错) ===
class Book: pass
class BookMetadata: pass
class Chapter: pass
class ChapterContent: pass
class TOCEntry: pass
class Section: pass
class Resource: pass
class Paragraph: pass
class Text: pass
# ====================================

def convert_pkl_to_txt(pkl_path):
    print(f"🚀 开始处理: {pkl_path}")

    if not os.path.exists(pkl_path):
        print(f"❌ 错误：找不到文件 {pkl_path}")
        return

    try:
        print("📖 正在解冻数据...")
        with open(pkl_path, 'rb') as f:
            book_data = pickle.load(f)

        output_path = pkl_path.replace('.pkl', '.txt')
        extracted_text = []

        print("✅ 解冻成功！")

        # === 核心提取逻辑：递归挖掘机 ===
        def extract_text(obj, level=0):
            # 1. 基础类型直接返回
            if isinstance(obj, str): return obj.strip()
            if isinstance(obj, (int, float, bool)): return ""
            if obj is None: return ""

            # 防止递归太深
            if level > 5: return ""

            results = []

            # 2. 如果是列表/元组 (比如 spine 本身就是个列表)
            if isinstance(obj, (list, tuple)):
                for item in obj:
                    results.append(extract_text(item, level + 1))

            # 3. 如果是字典
            elif isinstance(obj, dict):
                for v in obj.values():
                    results.append(extract_text(v, level + 1))

            # 4. 如果是对象 (Book, Chapter 等)
            elif hasattr(obj, '__dict__'):
                # 优先寻找像文本的属性
                priority_attrs = ['content', 'text', 'raw_text', '_content', 'lines', 'paragraphs']
                found_text = False

                # 先看有没有直接的文本属性
                for attr in priority_attrs:
                    if hasattr(obj, attr):
                        val = getattr(obj, attr)
                        if val:
                            results.append(extract_text(val, level + 1))
                            found_text = True

                # 如果没有显式文本属性，就遍历所有属性试试
                if not found_text:
                    for val in obj.__dict__.values():
                        results.append(extract_text(val, level + 1))

            return "\n".join(filter(None, results))

        # === 针对你的数据结构进行提取 ===

        # 1. 尝试提取书名 (metadata)
        if hasattr(book_data, 'metadata'):
            meta_text = extract_text(book_data.metadata)
            if meta_text:
                extracted_text.append(f"《书籍元数据》\n{meta_text}\n{'='*30}\n")

        # 2. 重点进攻：spine (章节列表)
        if hasattr(book_data, 'spine'):
            print(f"🎯 锁定目标：发现 'spine' 列表，长度: {len(book_data.spine)}")
            for i, item in enumerate(book_data.spine):
                # 尝试提取这一节的文本
                chapter_text = extract_text(item)

                # 如果提取到了内容，才写入
                if len(chapter_text) > 10: # 忽略太短的碎片
                    extracted_text.append(f"\n\n=== 第 {i+1} 部分 ===\n\n{chapter_text}")
                    # 打印进度条
                    if i % 5 == 0: print(f"   -> 已提取第 {i+1} 部分...")
        else:
            print("⚠️ 奇怪，这次没找到 spine？尝试全量暴力提取...")
            extracted_text.append(extract_text(book_data))

        # === 写入文件 ===
        if extracted_text:
            final_content = "\n".join(extracted_text)
            with open(output_path, 'w', encoding='utf-8') as f_out:
                f_out.write(final_content)

            print("\n🎉 胜利！提取完成！")
            print(f"📄 文件大小: {len(final_content)} 字符")
            print(f"👉 文本文件已保存至: {output_path}")
        else:
            print("❌ 依然没有提取到文本。这说明 spine 里的对象结构非常特殊。")
            # 终极调试：打印 spine里第一个对象到底长啥样
            if hasattr(book_data, 'spine') and len(book_data.spine) > 0:
                first_item = book_data.spine[0]
                print(f"调试：spine[0] 的类型: {type(first_item)}")
                print(f"调试：spine[0] 的属性: {dir(first_item)}")

    except Exception as e:
        print(f"\n❌ 程序崩溃: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        convert_pkl_to_txt(sys.argv[1])
    else:
        print("请提供 .pkl 文件路径")
