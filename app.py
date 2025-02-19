from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import List, Optional, Set
import os
import random
import json
from urllib.parse import unquote
from threading import Thread

app = Flask(_name_)
CORS(app)
load_dotenv()

api_key = os.getenv('OPENAI_API_KEY')
client = OpenAI(api_key=api_key)

class QuizQuestion(BaseModel):
    question: str
    options: List[str]
    answer: str
    explanation: str

question_cache: List[QuizQuestion] = []
used_questions: Set[str] = set()
current_topic: str = ""

def print_question(q: QuizQuestion, index: int):
    print(f"\nQuestion {index}:")
    print("=" * 50)
    print(f"Q: {q.question}")
    print("\nOptions:")
    for i, opt in enumerate(q.options):
        print(f"{chr(65+i)}) {opt}")
    print(f"\nCorrect Answer: {q.answer}")
    print(f"Explanation: {q.explanation}")
    print("-" * 50)

def read_chapter_content(file_path: str) -> str:
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()
    except Exception as e:
        print(f"Error reading file: {str(e)}")
        return None

def calculate_accuracy(text_content: str, questions: list) -> float:
    try:
        total_words = len(text_content.split())
        relevant_count = 0
        
        for q in questions:
            question_words = q.question.lower().split()
            for word in question_words:
                if len(word) > 3 and word in text_content.lower():
                    relevant_count += 1
        
        accuracy = min((relevant_count / (len(questions) * 2)) * 100, 100)
        return round(accuracy, 2)
    except Exception as e:
        print(f"Error calculating accuracy: {str(e)}")
        return 0.0

def generate_quiz_questions(text_content: str) -> Optional[List[QuizQuestion]]:
   system_prompt = """Generate 5 multiple choice questions in JSON format:
   1. Test logical reasoning 
   2. Explanation under 50 words
   3. Four answer options
   4. One correct answer
   
   Return in JSON format:
   {
       "questions": [
           {
               "question": "Question text",
               "options": ["Option 1", "Option 2", "Option 3", "Option 4"],
               "answer": "Correct option text", 
               "explanation": "Brief explanation"
           }
       ]
   }"""

   try:
       completion = client.chat.completions.create(
           model="gpt-4-turbo-preview",
           messages=[
               {"role": "system", "content": system_prompt},
               {"role": "user", "content": f"Content in JSON format:\n{text_content}"}
           ],
           temperature=0.7,
           response_format={"type": "json_object"}
       )

       response_data = json.loads(completion.choices[0].message.content)
       processed_questions = []

       for q in response_data["questions"]:
           if (not all(k in q for k in ["question", "options", "answer", "explanation"]) 
               or len(q["options"]) != 4
               or q["answer"] not in q["options"]
               or len(q["explanation"].split()) > 50):
               continue

           question = QuizQuestion(
               question=q["question"],
               options=q["options"], 
               answer=q["answer"],
               explanation=q["explanation"]
           )

           random.shuffle(question.options)
           processed_questions.append(question)

       return processed_questions

   except Exception as e:
       print(f"Error: {str(e)}")
       return None

def preload_questions(standard: str, subject: str, chapter: str, topic: str):
    global question_cache, current_topic, used_questions
    
    if topic != current_topic:
        question_cache.clear()
        used_questions.clear()
        current_topic = topic
    
    file_path = f"/home/ec2-user/schoolbooks/{standard}/{subject}/{topic}.txt"
    
    if os.path.exists(file_path):
        chapter_content = read_chapter_content(file_path)
        if chapter_content:
            questions = generate_quiz_questions(text_content=chapter_content)
            if questions:
                accuracy = calculate_accuracy(chapter_content, questions)
                print(f"\nQuestion Generation Accuracy: {accuracy}%")
                question_cache.extend(questions)

@app.route('/quiz/next', methods=['GET'])
def get_next_questions():
    try:
        topic = unquote(request.args.get('topic', ''))
        current_index = int(request.args.get('current_index', 0))
        standard = request.args.get('standard', '')
        subject = request.args.get('subject', '')
        chapter = request.args.get('chapter', '')

        if not all([topic, standard, subject]):
            return jsonify({"error": "Missing required parameters"}), 400

        if current_index % 5 == 2 or len(question_cache) < 5:
            Thread(target=preload_questions, args=(standard, subject, chapter, topic)).start()

        if len(question_cache) < 5:
            file_path = f"/home/ec2-user/schoolbooks/{standard}/{subject}/{topic}.txt"
            if os.path.exists(file_path):
                chapter_content = read_chapter_content(file_path)
                questions = generate_quiz_questions(text_content=chapter_content)
                if questions is None:
                    return jsonify({"error": "Failed to generate questions"}), 500
            else:
                return jsonify({"error": "Chapter file not found"}), 404
        else:
            questions = question_cache[:5]
            del question_cache[:5]

        return jsonify({
            "questions": [q.model_dump() for q in questions],
            "should_fetch": True
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"}), 200

@app.route('/quiz/clear-cache', methods=['GET'])
def clear_cache():
    global question_cache, used_questions
    question_cache.clear()
    used_questions.clear()
    return jsonify({"status": "Cache cleared"}), 200

if _name_ == '_main_':
    CORS(app, resources={r"/": {"origins": ""}})
    app.run(debug=True)
