import json
import os

def format_heading(text):
    return text.upper().replace("?", "")

def knowledgebase_to_rag_text(knowledge_json: str) -> str:
    data = json.loads(knowledge_json)
    output = ["DATA_AVAILABLE: TRUE\n"]

    # Contents
    contents = ["CONTENTS"]
    idx = 1
    if "about" in data:
        contents.append(f"{idx}. ABOUT WHIPSMART")
        idx += 1
    if "sections" in data:
        for section in data["sections"].values():
            contents.append(f"{idx}. {format_heading(section.get('title', ''))}")
            idx += 1
    if "faq" in data:
        contents.append(f"{idx}. FREQUENTLY ASKED QUESTIONS")
        idx += 1
    if "summary" in data:
        contents.append(f"{idx}. SUMMARY")
    output.append('\n'.join(contents) + '\n')

    # About
    if "about" in data:
        # output.append("===\nABOUT WHIPSMART\n")
        for section in data["about"]:
            output.append(format_heading(section.get("title", "")))
            for line in section.get("content", []):
                output.append(line)
            output.append("")

    # Sections
    if "sections" in data:
        for section in data["sections"].values():
            output.append("===\n" + format_heading(section.get("title", "")))
            if section.get("subtitle"):
                output.append(section["subtitle"])
            for item in section.get("items", []):
                output.append(f"{format_heading(item.get('title',''))}\n{item.get('description','')}")
                if item.get("links"):
                    for link in item["links"]:
                        output.append(f"LINK: {link['text']} ({link['url']})")
            output.append("")

    # FAQ
    if "faq" in data:
        output.append("===\nFREQUENTLY ASKED QUESTIONS\n")
        for faq in data["faq"]:
            q = format_heading(faq.get("question", ""))
            a = faq.get("answer", "")
            output.append(f"Q: {q}\nA: {a}\n")

    # Summary
    if "summary" in data:
        output.append("===\nSUMMARY")
        if "note" in data["summary"]:
            output.append(f"NOTE: {data['summary']['note']}")
        if "text" in data["summary"]:
            output.append(data["summary"]["text"])

    # Join with single newlines for plain text
    return "\n".join(output).replace("\n\n\n", "\n\n")

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(script_dir, "assets", "whipsmart_data.json")
    with open(json_path, "r", encoding="utf-8") as f:
        kb_json = f.read()

    formatted_text = knowledgebase_to_rag_text(kb_json)
    formatted_text_path = os.path.join(script_dir, "assets", "knowledgebase_formatted.txt")
    with open(formatted_text_path, "w", encoding="utf-8") as f:
        f.write(formatted_text)
    print("✅ Knowledgebase has been converted for RAG style and saved to knowledgebase_formatted.txt")
