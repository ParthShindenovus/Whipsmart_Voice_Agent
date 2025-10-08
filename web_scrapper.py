import requests
from bs4 import BeautifulSoup
import json
import os

ABOUT_URL = "https://whipsmart.au/about/"
FAQ_URL = "https://whipsmart.au/faq/"

def scrape_about_page(url):
    res = requests.get(url)
    soup = BeautifulSoup(res.text, "html.parser")
    
    # --- About Section (deduplicated) ---
    about_sections = []
    seen_titles = set()
    
    for block in soup.select("div.grid-block"):
        title_tag = block.find("h3")
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        
        # Skip duplicates
        if title in seen_titles:
            continue
        seen_titles.add(title)

        content = [p.get_text(strip=True) for p in block.find_all("p") if not p.find("a")]
        links = [{"text": a.get_text(strip=True), "url": a["href"]} for a in block.find_all("a", href=True)]
        
        about_sections.append({
            "title": title,
            "content": content,
            "links": links if links else None
        })

    # --- Dynamic Card Sections (Process / Benefits) ---
    sections = {}
    for section_wrapper in soup.select(".grid-block"):
        # Get section title
        title_tag = section_wrapper.find("h2")
        if not title_tag:
            continue
        section_title = title_tag.get_text(strip=True)
        subtitle_tag = section_wrapper.find("p")
        subtitle = subtitle_tag.get_text(strip=True) if subtitle_tag else None

        # Extract cards
        cards_data = []
        for card in section_wrapper.select(".card"):
            number_tag = card.select_one(".number")
            number = int(number_tag.get_text(strip=True)) if number_tag else None
            card_title = card.select_one(".title").get_text(strip=True) if card.select_one(".title") else None
            content_tag = card.select_one(".content")
            content = content_tag.get_text(" ", strip=True) if content_tag else None
            icon_tag = card.select_one("img")
            icon = icon_tag["src"] if icon_tag else None
            links = [{"text": a.get_text(strip=True), "url": a["href"]} for a in content_tag.find_all("a", href=True)] if content_tag else None
            
            cards_data.append({
                "number": number,
                "title": card_title,
                "description": content,
                "icon": icon,
                "links": links if links else None
            })

        sections[section_title] = {
            "title": section_title,
            "subtitle": subtitle,
            "items": cards_data
        }

    # --- Summary Section ---
    summary_section = {}
    summary_div = soup.select_one(".novated-leases-offer")
    if summary_div:
        note_tag = summary_div.find("strong")
        text_tag = summary_div.find_all("p")
        note = note_tag.get_text(strip=True) if note_tag else None
        text = text_tag[-1].get_text(strip=True) if text_tag else None
        summary_section = {"note": note, "text": text}

    return {
        "about": about_sections,
        "sections": sections,
        "summary": summary_section
    }

def scrape_faq_page(url):
    res = requests.get(url)
    soup = BeautifulSoup(res.text, "html.parser")
    faq_data = []
    faq_items = soup.select(".accordion-item")
    
    for item in faq_items:
        question_tag = item.select_one(".expander span")
        answer_tag = item.select_one(".expander-target")
        if question_tag and answer_tag:
            question = question_tag.get_text(strip=True)
            answer = " ".join([p.get_text(strip=True) for p in answer_tag.find_all("p")])
            faq_data.append({"question": question, "answer": answer})
    
    return {"faq": faq_data}

def main():
    data = scrape_about_page(ABOUT_URL)
    data.update(scrape_faq_page(FAQ_URL))
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(script_dir, "assets", "whipsmart_data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print("✅ All data scraped and saved to whipsmart_data.json")

if __name__ == "__main__":
    main()
