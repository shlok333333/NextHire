from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, session, url_for, redirect
import mysql.connector
from code_runner import run_python_code
from math import ceil
import os
import uuid
from werkzeug.utils import secure_filename
from pypdf import PdfReader
from docx import Document
from resume_analyzer import analyze_resume
from dotenv import load_dotenv
load_dotenv(override=True)


DB_HOST = os.getenv("DB_HOST") or "localhost"
DB_USER = os.getenv("DB_USER") or "root"
DB_PASSWORD = os.getenv("DB_PASSWORD") or ""
DB_NAME = os.getenv("DB_NAME") or "nexthire"
DB_PORT = int(os.getenv("DB_PORT") or "3306")

db = mysql.connector.connect(host=DB_HOST,user=DB_USER,password=DB_PASSWORD,database=DB_NAME,port=DB_PORT)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"]=os.path.join(app.root_path,"uploads","resumes")
app.config["MAX_CONTENT_LENGTH"]=5*1024*1024
ALLOWED_EXTENSIONS={"pdf","docx"}
os.makedirs(app.config["UPLOAD_FOLDER"],exist_ok=True)
app.secret_key=os.getenv("FLASK_SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("FLASK_SECRET_KEY is not configured")
def allowed_file(filename):
    return "." in filename and filename.rsplit(".",1)[1].lower() in ALLOWED_EXTENSIONS

def extract_resume_path(file_path):
    extension=file_path.rsplit(".",1)[1].lower()
    extracted_text=""
    if extension=="pdf":
        pdf=PdfReader(file_path)
        for page in pdf.pages:
            page_text=page.extract_text() or ""
            extracted_text+=page_text +"\n"
    elif extension=="docx":
        document=Document(file_path)
        for paragraph in document.paragraphs:
            extracted_text+=paragraph.text +"\n"
        for table in document.tables:
            for row in table.rows:
                for cell in table.cells:
                    extracted_text+=cell.text+"\n"
    return extracted_text.strip()

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/courses")
def courses():
    return render_template("courses.html")

@app.route("/resume", methods=["GET","POST"])
def resume_analyzer():
    if "user_id" not in session:
        return redirect(url_for("login/html"))
    if request.method=="POST":
        if "resume" not in request.files:
            return render_template("resume_upload.html",message="Please select a resume")
        file=request.files["resume"]
        if file.filename=="":
            return render_template("resume_upload.html",message="No file selected")
        if not allowed_file(file.filename):
            return render_template("resume_upload.html",message="Only PDF and DOCX are allowed")
        og_filename=secure_filename(file.filename)
        extension=og_filename.rsplit(".",1)[1].lower()
        unique_filename=f"{uuid.uuid4().hex}.{extension}"
        file_path=os.path.join(app.config["UPLOAD_FOLDER"], unique_filename)
        file.save(file_path)
        extracted_text=extract_resume_path(file_path)
        if not extracted_text:
            return render_template("resume_upload.html",message="Could not extract text, upload a text based PDF or DOCX")
        report=analyze_resume(extracted_text)
        missing_sections=",".join(report["missing_sections"])
        missing_keywords=",".join(report["missing_keywords"])
        suggestions="\n".join(report["suggestions"])
        cursor=db.cursor()
        cursor.execute("insert into resume_analysis(user_id,filename,ats_score,resume_text,missing_sections,missing_keywords,suggestions) values(%s, %s, %s, %s, %s, %s, %s)",(session["user_id"],og_filename,report["total_score"],extracted_text,missing_sections,missing_keywords,suggestions))
        db.commit()
        analysis_id=cursor.lastrowid
        cursor.close()
        return render_template("resume_result.html",report=report,filename=og_filename,analysis_id=analysis_id)
    return render_template("resume_upload.html")

@app.route("/coding")
def coding():
    diff=request.args.get("difficulty")
    find=request.args.get("search")
    page=request.args.get("page", 1, type=int)
    sort=request.args.get("sort", "newest")
    topic=request.args.get("topic")
    cursor = db.cursor(dictionary=True)
    per_page = 5
    offset = (page - 1) * per_page
    query = "SELECT * FROM coding WHERE 1=1"
    param = []
    if diff:
        query += " AND difficulty=%s"
        param.append(diff)
    if topic:
        query += " and topic=%s"
        param.append(topic)
    if find:
        query += " AND title LIKE %s"
        param.append("%" + find + "%")
    if sort == "oldest":
        query += " ORDER BY id ASC"
    elif sort == "title_asc":
        query += " ORDER BY title ASC"
    elif sort == "title_desc":
        query += " ORDER BY title DESC"
    else:
        query += " ORDER BY id DESC"
    query += " LIMIT %s OFFSET %s"
    param.extend([per_page, offset])
    cursor.execute(query, param)
    problems = cursor.fetchall()
    cursor.execute("""SELECT DISTINCT problem_id FROM coding_submission WHERE user_id=%s AND status='Correct Answer ✅'""",(session["user_id"],))
    solved_rows = cursor.fetchall()
    solved = {row["problem_id"] for row in solved_rows}
    count_query = "SELECT COUNT(*) AS total FROM coding WHERE 1=1"
    count_params = []
    if diff:
        count_query += " AND difficulty=%s"
        count_params.append(diff)
    if topic:
        count_query += " AND topic=%s"
        count_params.append(topic)
    if find:
        count_query += " AND title LIKE %s"
        count_params.append("%" + find + "%")
    cursor.execute(count_query, count_params)
    total_problems = cursor.fetchone()["total"]
    total_pages = ceil(total_problems / per_page)
    cursor.close()
    return render_template("coding.html", topic=topic,solved=solved,sort=sort,page=page,problems=problems,difficulty=diff,search=find,total_pages=total_pages,total_problems=total_problems)

@app.route("/coding/<int:problem_id>", methods=["GET","POST"])
def coding_problem(problem_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    cursor=db.cursor(dictionary=True)
    cursor.execute("select * from coding where id=%s",(problem_id,))
    problem=cursor.fetchone()
    cursor.execute("select * from coding_test_cases where problem_id=%s",(problem_id,))
    test_cases=cursor.fetchall()
    cursor.execute("select * from coding_submission where user_id=%s and problem_id=%s order by submitted_at desc",(session["user_id"],problem_id))
    history=cursor.fetchall()
    cursor.close()
    submitted_code=request.form.get("code")
    custom_input=request.form.get("custom_input")
    action=request.form.get("action")
    result=None
    flag = True
    output = ""
    error = ""
    exp_output = ""
    passed_tests=0
    failed_test=None
    if action=="run":
        output, error=run_python_code(submitted_code, custom_input)
    elif action=="submit":
        if request.method == "POST":
            for test_case in test_cases:
                test_output, test_error = run_python_code(submitted_code, test_case["input_data"])
                if test_error:
                    result = "Runtime Error ❌"
                    error = test_error
                    output = test_output
                    failed_test= test_case["id"]
                    flag = False
                    break

                if test_output.strip() != test_case["expected_output"].strip():
                    result = "Wrong Answer ❌"
                    output = test_output
                    failed_test= test_case["id"]
                    exp_output=test_case["expected_output"]
                    flag = False
                    break
                passed_tests+=1

            if flag:
                result = "Correct Answer ✅"
            cursor=db.cursor()
            cursor.execute("insert into coding_submission(user_id, problem_id, code, status, passed_tests, total_tests) values(%s, %s, %s, %s, %s, %s)",(session["user_id"], problem_id, submitted_code, result, passed_tests, len(test_cases)))
            db.commit()
            cursor.close()
    return render_template("coding_problem.html", exp_output=exp_output, history=history, problem=problem, submitted_code=submitted_code,output=output, error=error, passed_tests=passed_tests, result=result, test_cases=test_cases, failed_test=failed_test)

@app.route("/aptitude")
def aptitude():
    if "user_id" not in session:
        return redirect(url_for("login"))
    tests = [
        {"number": 1, "difficulty": "Easy", "questions": 10},
        {"number": 2, "difficulty": "Easy", "questions": 10},
        {"number": 3, "difficulty": "Easy", "questions": 10},

        {"number": 4, "difficulty": "Medium", "questions": 10},
        {"number": 5, "difficulty": "Medium", "questions": 10},
        {"number": 6, "difficulty": "Medium", "questions": 10},

        {"number": 7, "difficulty": "Hard", "questions": 10},
        {"number": 8, "difficulty": "Hard", "questions": 10},
        {"number": 9, "difficulty": "Hard", "questions": 10},

        {"number": 10, "difficulty": "Mixed", "questions": 25}
    ]
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT test_number, score, total FROM results WHERE user_id = %s AND category = 'aptitude' ORDER BY attempted_at DESC",(session["user_id"],))
    results = cursor.fetchall()
    cursor.close()
    test_results = {}
    for result in results:
        test_number = result["test_number"]
        if test_number not in test_results:
            test_results[test_number] = result
    tests_completed = len(test_results)
    questions_attempted = 0
    questions_correct = 0
    for result in test_results.values():
        questions_attempted += result["total"]
        questions_correct += result["score"]
    if questions_attempted > 0:
        accuracy = round((questions_correct / questions_attempted) * 100)
    else:
        accuracy = 0
    progress = round((tests_completed / len(tests)) * 100)
    return render_template("aptitude.html",tests=tests,test_results=test_results, accuracy=accuracy, progress=progress)

@app.route("/aptitude/test/<int:test_number>", methods=["GET", "POST"])
def aptitude_test(test_number):
    if "user_id" not in session:
        return redirect(url_for("login"))
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM questions WHERE category = 'aptitude' AND test_number = %s ORDER BY id",(test_number,))
    questions = cursor.fetchall()
    if request.method == "POST":
        score = 0
        result_details = []
        for question in questions:
            user_answer = request.form.get(f"question_{question['id']}")
            correct_answer = question["correct_answer"]
            if user_answer == correct_answer:
                score += 1
                is_correct = True
            else:
                is_correct = False
            result_details.append({
                "question": question["question"],
                "user_answer": user_answer,
                "correct_answer": correct_answer,
                "is_correct": is_correct,
                "option_a": question["option_a"],
                "option_b": question["option_b"],
                "option_c": question["option_c"],
                "option_d": question["option_d"]
            })
        total = len(questions)
        cursor.execute(
            "INSERT INTO results(user_id, category, test_number, score, total) VALUES (%s, %s, %s, %s, %s)",(session["user_id"],"aptitude",test_number,score,total ))
        db.commit()
        cursor.close()
        return render_template("aptitude_result.html",score=score,total=total,test_number=test_number,result_details=result_details)
    cursor.close()
    return render_template("aptitude_test.html",questions=questions,test_number=test_number)

@app.route("/interview")
def interview():
    if "user_id" not in session:
        return redirect(url_for("login"))
    categories = [
        {
            "name": "HR",
            "title": "HR & General Interview",
            "description": "Prepare for common HR and general interview questions.",
            "icon": "👤"
        },
        {
            "name": "EE Technical",
            "title": "EE Technical Interview",
            "description": "Prepare for Electrical Engineering technical interviews.",
            "icon": "⚡"
        },
        {
            "name": "Programming & CS",
            "title": "Programming & CS Basics",
            "description": "Revise programming, data structures, algorithms and database concepts.",
            "icon": "💻"
        },
        {
            "name": "Behavioral",
            "title": "Behavioral & Situational",
            "description": "Practice real-world workplace and behavioral interview questions.",
            "icon": "🧠"
        }
    ]
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT iq.category,COUNT(iq.id) AS total_questions,COUNT(ip.question_id) AS practiced_questions FROM interview_questions iq LEFT JOIN interview_progress ip ON iq.id = ip.question_id AND ip.user_id = %s GROUP BY iq.category",(session["user_id"],))
    progress_data = cursor.fetchall()
    cursor.close()
    progress_map = {}
    for row in progress_data:
        progress_map[row["category"]] = row
    for category in categories:
        progress = progress_map.get(category["name"],{"total_questions": 0,"practiced_questions": 0})
        category["total_questions"] = progress["total_questions"]
        category["practiced_questions"] = progress["practiced_questions"]
        if category["total_questions"] > 0:
            category["percentage"] = round((category["practiced_questions"]/category["total_questions"]) * 100)
        else:
            category["percentage"] = 0
    return render_template("interview.html",categories=categories)

@app.route("/interview/<category>/<int:question_number>")
def interview_question(category, question_number):
    if "user_id" not in session:
        return redirect(url_for("login"))
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM interview_questions WHERE category = %s ORDER BY id",(category,))
    questions = cursor.fetchall()
    cursor.close()
    if not questions:
        return redirect(url_for("interview"))
    if question_number < 1 or question_number > len(questions):
        return redirect(url_for("interview_question",category=category,question_number=1))
    question = questions[question_number - 1]
    cursor = db.cursor()
    cursor.execute("INSERT IGNORE INTO interview_progress(user_id, question_id) VALUES (%s, %s)",(session["user_id"],question["id"]))
    db.commit()
    cursor.close()
    return render_template("interview_question.html",question=question,category=category,question_number=question_number,total_questions=len(questions))

@app.route("/interview/mock/start")
def start_mock_interview():
    if "user_id" not in session:
        return redirect(url_for("login"))
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT id FROM interview_questions ORDER BY RAND() LIMIT 10")
    questions = cursor.fetchall()
    if len(questions) < 10:
        cursor.close()
        return redirect(url_for("interview"))
    cursor.execute("INSERT INTO mock_interviews(user_id, total_questions) VALUES (%s, %s)",(session["user_id"], len(questions)))
    mock_interview_id = cursor.lastrowid
    for number, question in enumerate(questions, start=1):
        cursor.execute("INSERT INTO mock_interview_questions(mock_interview_id, question_id, question_number) VALUES (%s, %s, %s)",(mock_interview_id,question["id"],number))
    db.commit()
    cursor.close()
    return redirect(url_for("mock_question",mock_id=mock_interview_id,question_number=1))

@app.route(
    "/interview/mock/<int:mock_id>/<int:question_number>",
    methods=["GET", "POST"]
)
def mock_question(mock_id, question_number):
    if "user_id" not in session:
        return redirect(url_for("login"))
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT miq.question_number,iq.id,iq.question,iq.category,iq.difficulty,iq.what_interviewer_expects,iq.sample_answer,iq.key_points, iq.common_mistakes FROM mock_interview_questions miq JOIN mock_interviews mi ON miq.mock_interview_id = mi.id JOIN interview_questions iq ON miq.question_id = iq.id WHERE miq.mock_interview_id = %s AND miq.question_number = %s AND mi.user_id = %s",(mock_id,question_number,session["user_id"]))
    question = cursor.fetchone()
    if not question:
        cursor.close()
        return redirect(url_for("interview"))
    if request.method == "POST":
        user_answer = request.form.get("user_answer")
        cursor.execute("INSERT INTO mock_interview_answers(mock_interview_id, question_id, user_answer) VALUES (%s, %s, %s)",(mock_id,question["id"],user_answer))
        db.commit()
        cursor.close()
        return render_template("mock_answer.html",question=question,user_answer=user_answer,mock_id=mock_id,question_number=question_number)
    cursor.close()
    return render_template("mock_interview.html",question=question,mock_id=mock_id,question_number=question_number)

@app.route("/interview/mock/<int:mock_id>/complete")
def complete_mock_interview(mock_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM mock_interviews WHERE id = %s AND user_id = %s",(mock_id,session["user_id"]))
    mock = cursor.fetchone()
    if not mock:
        cursor.close()
        return redirect(url_for("interview"))
    cursor.execute("UPDATE mock_interviews SET completed_at = CURRENT_TIMESTAMP WHERE id = %s",(mock_id,))
    db.commit()
    cursor.close()
    return redirect(url_for("mock_result",mock_id=mock_id))

@app.route("/interview/mock/<int:mock_id>/result")
def mock_result(mock_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT mi.id, mi.total_questions, mi.started_at, mi.completed_at, COUNT(mia.id) AS answered_questions FROM mock_interviews mi LEFT JOIN mock_interview_answers mia ON mi.id = mia.mock_interview_id WHERE mi.id = %s AND mi.user_id = %s GROUP BY mi.id, mi.total_questions, mi.started_at, mi.completed_at",(mock_id,session["user_id"]))
    mock = cursor.fetchone()
    cursor.close()
    if not mock:
        return redirect(url_for("interview"))
    return render_template("mock_result.html",mock=mock)

@app.route("/interview/mock/history")
def mock_history():
    if "user_id" not in session:
        return redirect(url_for("login"))
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT mi.id, mi.total_questions, mi.started_at, mi.completed_at, COUNT(mia.id) AS answered_questions FROM mock_interviews mi LEFT JOIN mock_interview_answers mia ON mi.id = mia.mock_interview_id WHERE mi.user_id = %s GROUP BY mi.id, mi.total_questions, mi.started_at, mi.completed_at ORDER BY mi.started_at DESC",(session["user_id"],))
    mock_interviews = cursor.fetchall()
    cursor.close()
    return render_template("mock_history.html",mock_interviews=mock_interviews)

@app.route("/core")
def core():
    if "user_id" not in session:
        return redirect(url_for("login"))
    sections = [
        {
            "number": 1,
            "title": "Circuit Theory & Network Analysis",
            "questions": 25
        },
        {
            "number": 2,
            "title": "Electrical Machines & Power Systems",
            "questions": 25
        },
        {
            "number": 3,
            "title": "Analog & Digital Electronics",
            "questions": 25
        },
        {
            "number": 4,
            "title": "Control Systems, Measurements & Signals",
            "questions": 25
        }
    ]
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT section_number, score, total FROM ee_results WHERE user_id = %s ORDER BY attempted_at DESC",(session["user_id"],))
    results = cursor.fetchall()
    cursor.close()
    section_results = {}
    for result in results:
        section_number = result["section_number"]
        if section_number not in section_results:
            section_results[section_number] = result
    sections_completed = len(section_results)
    questions_attempted = 0
    questions_correct = 0
    for result in section_results.values():
        questions_attempted += result["total"]
        questions_correct += result["score"]
    if questions_attempted > 0:
        accuracy = round((questions_correct / questions_attempted) * 100)
    else:
        accuracy = 0
    progress = round((sections_completed / len(sections)) * 100)
    return render_template("core.html",sections=sections,section_results=section_results,sections_completed=sections_completed,questions_attempted=questions_attempted,questions_correct=questions_correct,accuracy=accuracy,progress=progress)

@app.route("/core/section/<int:section_number>", methods=["GET", "POST"])
def core_section(section_number):
    if "user_id" not in session:
        return redirect(url_for("login"))
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM ee_questions WHERE section_number = %s ORDER BY id",(section_number,))
    questions = cursor.fetchall()
    if request.method == "POST":
        score = 0
        result_details = []
        for question in questions:
            user_answer = request.form.get(f"question_{question['id']}")
            correct_answer = question["correct_answer"]
            if user_answer == correct_answer:
                score += 1
                is_correct = True
            else:
                is_correct = False
            result_details.append({"question": question["question"],"user_answer": user_answer,"correct_answer": correct_answer,"is_correct": is_correct,"explanation": question["explanation"]})
        total = len(questions)
        cursor.execute("INSERT INTO ee_results(user_id, section_number, score, total) VALUES(%s, %s, %s, %s)",(session["user_id"],section_number,score,total))
        db.commit()
        cursor.close()
        return render_template("core_result.html",section_number=section_number,score=score,total=total,result_details=result_details)
    cursor.close()
    return render_template("core_test.html",questions=questions,section_number=section_number)

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        email=request.form["email"]
        password=request.form["password"]
        if email=="" or password=="":
            return "Please enter both email and password!"
        cursor=db.cursor()
        cursor.execute("select * from users where email=%s",(email,))
        present=cursor.fetchone()
        if present:
            stored_pass=present[3]
            if check_password_hash(stored_pass, password):
                session["user_id"]=present[0]
                session["user_name"]=present[1]
                return redirect(url_for("dashboard"))
            else:
                return "Invalid Details!"
        else:
            return "No Account found!"
    return render_template("login.html")

@app.route("/signup", methods=["GET","POST"])
def signup():
    if request.method=="POST":
        name=request.form["name"]
        email=request.form["email"]
        password=request.form["password"]
        hash_password=generate_password_hash(password)
        if name=="" or email=="" or password=="":
            return "Please enter all the fields!"
        cursor=db.cursor()
        cursor.execute("select * from users where email=%s",(email,))
        present=cursor.fetchone()
        if present:
            return "Login Instead!"
        else:
            cursor.execute("insert into users(name, email, password) values(%s, %s, %s)",(name,email,hash_password))
            db.commit()
            return redirect(url_for("login"))
    return render_template("signup.html")

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return "Please login first!"
    cursor=db.cursor(dictionary=True)
    cursor.execute("select count(distinct problem_id) as solved_count from coding_submission where user_id=%s and status='Correct Answer ✅'",(session["user_id"],))
    coding_progress=cursor.fetchone()
    cursor.close()
    coding_solved=coding_progress["solved_count"]
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) AS total FROM coding")
    coding_total = cursor.fetchone()["total"]
    cursor.close()
    if coding_total > 0:
        coding_percentage = round((coding_solved / coding_total) * 100)
    else:
        coding_percentage = 0
    cursor=db.cursor(dictionary=True)
    cursor.execute("select score, total from results where user_id=%s and category=%s order by attempted_at desc limit 1",(session["user_id"],"aptitude"))
    aptitude_result=cursor.fetchone()
    cursor.close()
    if aptitude_result:
        aptitude_percentage=round(aptitude_result["score"]/aptitude_result["total"]*100)
    else:
        aptitude_percentage=0
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(DISTINCT question_id) AS practiced_questions FROM interview_progress WHERE user_id = %s",(session["user_id"],))
    interview_progress = cursor.fetchone()
    interview_practiced = interview_progress["practiced_questions"]
    interview_total = 40
    interview_percentage = round((interview_practiced / interview_total) * 100)
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(DISTINCT section_number) AS completed_sections FROM ee_results WHERE user_id = %s",(session["user_id"],))
    ee_progress = cursor.fetchone()
    ee_completed = ee_progress["completed_sections"]
    ee_total_sections = 4
    ee_percentage = round((ee_completed / ee_total_sections) * 100)
    return render_template("dashboard.html", ee_completed=ee_completed, ee_total_sections=ee_total_sections, ee_percentage=ee_percentage,interview_practiced=interview_practiced, interview_total=interview_total, interview_percentage=interview_percentage,coding_total=coding_total, coding_percentage=coding_percentage,aptitude_percentage=aptitude_percentage, coding_solved=coding_solved)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))
        
if __name__ == "__main__":
    app.run(debug=True)