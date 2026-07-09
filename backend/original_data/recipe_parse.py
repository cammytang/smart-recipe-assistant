import json
import os
import re
from typing import Dict, List, Optional


# ===================== 配置区，按你实际路径修改 =====================
# dishes 文件夹路径
ROOT_DISHES_DIR = "./dishes"
# 解析结果输出 JSON 路径
OUTPUT_JSON_PATH = "./data/dishes.json"
# ===================================================================


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+?)\s*$")


def clean_text(text: str) -> str:
    """清理 Markdown 图片、HTML 注释和多余空白。"""
    text = HTML_COMMENT_RE.sub("", text)
    text = IMAGE_RE.sub("", text)
    text = text.replace("\u3000", " ")
    return re.sub(r"\s+", " ", text).strip()


def clean_dish_name(title: str, file_path: str) -> str:
    """把“xxx的做法”清洗成菜名；标题异常时回退到文件名。"""
    title = clean_text(title).strip("# ")
    dish_name = re.sub(r"的做法$", "", title).strip()
    if dish_name:
        return dish_name
    return os.path.splitext(os.path.basename(file_path))[0]


def get_category(file_path: str, root_dir: str) -> str:
    """取 dishes 下的第一层目录作为分类，兼容菜谱有二级图片目录的情况。"""
    rel_path = os.path.relpath(file_path, root_dir)
    parts = rel_path.split(os.sep)
    return parts[0] if len(parts) > 1 else "uncategorized"


def split_sections(md_content: str) -> Dict[str, List[str]]:
    """按 Markdown 标题切成章节，返回 title -> lines。"""
    sections: Dict[str, List[str]] = {"__intro__": []}
    current_title = "__intro__"

    for raw_line in md_content.splitlines():
        line = raw_line.rstrip()
        match = HEADING_RE.match(line)
        if match:
            level = len(match.group(1))
            title = clean_text(match.group(2))
            if level == 1:
                sections["__h1__"] = [title]
                current_title = "__intro__"
            else:
                current_title = title
                sections.setdefault(current_title, [])
            continue
        sections.setdefault(current_title, []).append(line)

    return sections


def parse_list_items(lines: List[str]) -> List[str]:
    """抽取无序/有序列表项。"""
    items = []
    for line in lines:
        line = clean_text(line)
        if not line:
            continue
        match = LIST_ITEM_RE.match(line)
        if match:
            items.append(clean_text(match.group(1)))
    return items


def parse_paragraphs(lines: List[str]) -> List[str]:
    """抽取普通段落，跳过图片和列表项。"""
    paragraphs = []
    for line in lines:
        text = clean_text(line)
        if not text or LIST_ITEM_RE.match(text):
            continue
        paragraphs.append(text)
    return paragraphs


def parse_metric(lines: List[str], prefix: str) -> Optional[str]:
    """从正文中抽取“预估烹饪难度：★★”这类字段。"""
    for line in lines:
        text = clean_text(line)
        if text.startswith(prefix):
            return text.split("：", 1)[-1].strip()
    return None


def find_section(sections: Dict[str, List[str]], keywords: List[str]) -> List[str]:
    """按关键词找章节内容。"""
    for title, lines in sections.items():
        if title.startswith("__"):
            continue
        if any(keyword in title for keyword in keywords):
            return lines
    return []


def build_search_text(recipe: Dict[str, object]) -> str:
    """拼接用于向量化检索的主文本。"""
    parts = [
        f"菜名：{recipe['dish_name']}",
        f"分类：{recipe['category']}",
    ]

    if recipe.get("description"):
        parts.append(f"简介：{recipe['description']}")
    if recipe.get("difficulty"):
        parts.append(f"难度：{recipe['difficulty']}")
    if recipe.get("calories"):
        parts.append(f"热量：{recipe['calories']}")
    if recipe.get("ingredients"):
        parts.append(f"必备原料和工具：{'、'.join(recipe['ingredients'])}")
    if recipe.get("serving_ingredients"):
        parts.append(f"每份用量：{'、'.join(recipe['serving_ingredients'])}")
    if recipe.get("steps"):
        parts.append(f"烹饪步骤：{'；'.join(recipe['steps'])}")
    if recipe.get("tips"):
        parts.append(f"附加内容：{'；'.join(recipe['tips'])}")

    return "\n".join(parts).strip()


def parse_single_recipe_md(file_path: str, root_dir: str = ROOT_DISHES_DIR):
    """
    解析单个菜谱 md 文件。

    返回适合作为 RAG 原始数据的结构化字典；无效菜谱返回 None。
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            md_content = f.read()
    except Exception as e:
        print(f"读取失败 {file_path}: {e}")
        return None

    sections = split_sections(md_content)
    title = sections.get("__h1__", [""])[0]
    dish_name = clean_dish_name(title, file_path)

    intro_lines = sections.get("__intro__", [])
    description_parts = []
    for paragraph in parse_paragraphs(intro_lines):
        if paragraph.startswith("预估烹饪难度") or paragraph.startswith("预估卡路里"):
            continue
        description_parts.append(paragraph)

    ingredient_lines = find_section(sections, ["必备原料", "食材", "原料"])
    calculation_lines = find_section(sections, ["计算", "用量", "份量"])
    step_lines = find_section(sections, ["操作", "做法", "步骤"])
    tip_lines = find_section(sections, ["附加内容", "小贴士", "注意事项"])

    ingredients = parse_list_items(ingredient_lines)
    serving_ingredients = parse_list_items(calculation_lines)
    steps = parse_list_items(step_lines)
    tips = parse_list_items(tip_lines)

    if not dish_name or not ingredients:
        return None

    rel_source_path = os.path.relpath(file_path, root_dir)
    recipe = {
        "id": os.path.splitext(rel_source_path)[0].replace(os.sep, "/"),
        "dish_name": dish_name,
        "category": get_category(file_path, root_dir),
        "difficulty": parse_metric(intro_lines, "预估烹饪难度"),
        "calories": parse_metric(intro_lines, "预估卡路里"),
        "description": " ".join(description_parts).strip(),
        "ingredients": ingredients,
        "serving_ingredients": serving_ingredients,
        "steps": steps,
        "tips": tips,
        "source_path": rel_source_path.replace(os.sep, "/"),
    }
    recipe["search_text"] = build_search_text(recipe)
    return recipe


def traverse_all_md_recipes(root_dir):
    """遍历全部 md，批量解析。"""
    all_recipes = []
    for parent_dir, _, files in os.walk(root_dir):
        for filename in sorted(files):
            if filename.lower().endswith(".md"):
                full_path = os.path.join(parent_dir, filename)
                result = parse_single_recipe_md(full_path, root_dir)
                if result:
                    all_recipes.append(result)
    return sorted(all_recipes, key=lambda item: item["source_path"])


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUTPUT_JSON_PATH), exist_ok=True)

    recipe_list = traverse_all_md_recipes(ROOT_DISHES_DIR)

    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(recipe_list, f, ensure_ascii=False, indent=2)

    print(f"解析完成，有效菜谱总数：{len(recipe_list)}")
    print(f"结果输出路径：{OUTPUT_JSON_PATH}")
