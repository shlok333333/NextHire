import re

def analyze_resume(text):
    text = text.lower()
    score = 0
    report = {}
    email = re.search(r'[\w\.-]+@[\w\.-]+\.\w+',text)
    phone = re.search(r'\b(?:\+91[\s-]?)?[6-9]\d{9}\b',text)
    contact_score = 0
    if email:
        contact_score += 5
    if phone:
        contact_score += 5
    report["contact"] = contact_score
    score += contact_score
    sections = {
        "education": ["education", "academic qualification"],
        "skills": ["skills", "technical skills"],
        "projects": ["projects", "academic projects"],
        "experience": ["experience", "internship", "work experience"]
    }
    section_score = 0
    missing_sections = []
    for section, keywords in sections.items():
        if any(keyword in text for keyword in keywords):
            section_score += 3
        else:
            missing_sections.append(section.title())
    report["sections"] = section_score
    score += section_score
    education_keywords = [
        "b.tech",
        "bachelor",
        "degree",
        "university",
        "college",
        "engineering",
        "diploma",
        "cgpa",
        "gpa"
    ]
    education_score = 0
    for keyword in education_keywords:
        if keyword in text:
            education_score += 2
    education_score = min(education_score, 10)
    report["education"] = education_score
    score += education_score
    technical_skills = [
        "python",
        "java",
        "c++",
        "sql",
        "mysql",
        "flask",
        "html",
        "css",
        "javascript",
        "react",
        "machine learning",
        "data structures",
        "algorithms",
        "git",
        "github"
    ]
    detected_skills = []
    for skill in technical_skills:
        if skill in text:
            detected_skills.append(skill)
    skills_score = min(len(detected_skills),15)
    report["skills"] = skills_score
    score += skills_score
    project_keywords = [
        "project",
        "developed",
        "built",
        "implemented",
        "designed"
    ]
    project_score = sum(3 for keyword in project_keywords if keyword in text)
    project_score = min(project_score, 15)
    report["projects"] = project_score
    score += project_score
    experience_keywords = [
        "internship",
        "intern",
        "work experience",
        "professional experience",
        "worked at",
        "employment"
    ]
    experience_score = sum(3 for keyword in experience_keywords if keyword in text)
    experience_score = min(experience_score, 15)
    report["experience"] = experience_score
    score += experience_score
    keywords = [
        "communication",
        "teamwork",
        "problem solving",
        "leadership",
        "analytical",
        "collaboration",
        "time management",
        "adaptability",
        "critical thinking",
        "responsibility"
    ]
    detected_keywords = [keyword for keyword in keywords if keyword in text]
    keyword_score = min(len(detected_keywords),10)
    report["keywords"] = keyword_score
    score += keyword_score
    formatting_score = 0
    if len(text.split()) >= 100:
        formatting_score += 5
    if "\n" in text:
        formatting_score += 5
    report["formatting"] = formatting_score
    score += formatting_score
    report["total_score"] = score
    report["missing_sections"] = missing_sections
    report["detected_skills"] = detected_skills
    report["detected_keywords"] = detected_keywords
    report["missing_keywords"] = [keyword for keyword in keywords if keyword not in text]
    report["suggestions"] = []
    if missing_sections:
        report["suggestions"].append("Consider adding these sections: "+ ", ".join(missing_sections))
    if contact_score < 10:
        report["suggestions"].append("Add both a valid email address and phone number.")
    if skills_score < 10:
        report["suggestions"].append("Include more relevant technical skills that you genuinely possess.")
    if project_score < 9:
        report["suggestions"].append("Describe your projects, your contributions and the technologies used.")
    if experience_score == 0:
        report["suggestions"].append("If you are a fresher, highlight academic projects, practical work or internships.")
    if formatting_score < 10:
        report["suggestions"].append("Use clear section headings and ensure the resume contains sufficient readable text.")
    return report
