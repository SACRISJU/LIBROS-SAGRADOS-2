"""
Backend server para Sabiduría de los Libros Sagrados
Conecta el chat web con NotebookLM via automatización de browser
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

NOTEBOOKLM_SKILL = Path(r"C:\Users\juans\.claude\skills\notebooklm")
NOTEBOOK_URL = "https://notebooklm.google.com/notebook/49176ae3-3a4a-4234-87b6-4ff8feda5b5a"
VENV_PYTHON = NOTEBOOKLM_SKILL / ".venv" / "Scripts" / "python.exe"

PROMPT_TEMPLATE = """Responde en español a: {question}

Usa EXACTAMENTE este formato, sin añadir nada más:

INTRO: [2-3 frases de introducción compasiva en español]

LIBRO: [libro sagrado, capítulo y verso] | RELIGION: [tradición] | TEXTO: "[cita textual exacta]"
LIBRO: [libro sagrado, capítulo y verso] | RELIGION: [tradición] | TEXTO: "[cita textual exacta]"
LIBRO: [libro sagrado, capítulo y verso] | RELIGION: [tradición] | TEXTO: "[cita textual exacta]"
LIBRO: [libro sagrado, capítulo y verso] | RELIGION: [tradición] | TEXTO: "[cita textual exacta]"
LIBRO: [libro sagrado, capítulo y verso] | RELIGION: [tradición] | TEXTO: "[cita textual exacta]"

Reglas: mínimo 3 citas, máximo 10, de distintas tradiciones (Biblia, Corán, Bhagavad Gita, Tao Te Ching, Tripitaka, Guru Granth Sahib, Talmud, Avesta, etc.). Todo en español."""


def query_notebooklm(question: str) -> str:
    """Llama al script de NotebookLM y devuelve la respuesta en texto plano."""
    import os
    prompt = PROMPT_TEMPLATE.format(question=question)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    result = subprocess.run(
        [
            str(VENV_PYTHON),
            str(NOTEBOOKLM_SKILL / "scripts" / "ask_question.py"),
            "--question", prompt,
            "--notebook-url", NOTEBOOK_URL,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        cwd=str(NOTEBOOKLM_SKILL),
        env=env,
    )

    output = result.stdout + result.stderr
    # Extraer solo la respuesta (entre los separadores de ===)
    match = re.search(r"={20,}\n\n(.+?)(?:EXTREMELY IMPORTANT|={20,})", output, re.DOTALL)
    if match:
        return match.group(1).strip()
    return output.strip()


def parse_response(raw: str) -> dict:
    """Parsea el texto de NotebookLM al formato JSON del frontend."""
    # Normalizar saltos de línea (Windows puede devolver \r\n)
    raw = raw.replace('\r\n', '\n').replace('\r', '\n')

    # --- Extraer INTRO ---
    # Buscar INTRO: en cualquier posición del texto
    intro = ""
    intro_match = re.search(r'(?i)INTRO:\s*(.+?)(?=\nLIBRO:|\Z)', raw, re.DOTALL)
    if intro_match:
        intro = intro_match.group(1).strip()
    else:
        # Si no hay INTRO:, tomar párrafo inicial antes del primer LIBRO:
        parts = re.split(r'\nLIBRO:', raw, maxsplit=1)
        if len(parts) > 1:
            intro = parts[0].strip()

    # Limpiar intro: quitar números de cita inline y "more_horiz"
    intro = re.sub(r'\n\d+\n', ' ', intro)
    intro = re.sub(r'\nmore_horiz\n?', '', intro)
    intro = re.sub(r'\n\d+$', '', intro)
    intro = re.sub(r'\s{2,}', ' ', intro).strip()

    # Las citas se extraen del texto completo
    citas_block = raw

    # --- Extraer CITAS ---
    citation_pattern = re.compile(
        r'LIBRO:\s*(.+?)\s*\|\s*RELIGION:\s*(.+?)\s*\|\s*TEXTO:\s*[\"\u201c\u00ab](.+?)[\"\u201d\u00bb]',
        re.IGNORECASE
    )
    citations = []
    for m in citation_pattern.finditer(citas_block):
        book     = m.group(1).strip()
        religion = m.group(2).strip()
        quote    = re.sub(r'\n\d+\n?', ' ', m.group(3)).strip()
        quote    = re.sub(r'\nmore_horiz\n?', '', quote).strip()
        if len(quote) >= 10:
            citations.append({"book": book, "religion": religion, "quote": quote})

    # Fallback parseo línea a línea
    if not citations:
        for line in citas_block.split('\n'):
            if 'LIBRO:' in line.upper() and '|' in line:
                parts = line.split('|')
                if len(parts) >= 3:
                    book_p = re.sub(r'(?i)libro:', '', parts[0]).strip()
                    rel_p  = re.sub(r'(?i)religion:', '', parts[1]).strip()
                    quo_p  = re.sub(r'(?i)texto:', '', parts[2]).strip().strip('"\u201c\u201d')
                    if book_p and len(quo_p) >= 10:
                        citations.append({"book": book_p, "religion": rel_p, "quote": quo_p})

    if not intro:
        intro = "Los libros sagrados responden con sabiduría y compasión a tu pregunta."

    return {"intro": intro, "citations": citations[:10]}


@app.route('/debug/raw', methods=['POST'])
def debug_raw():
    data = request.get_json()
    q = data.get('question', 'test')
    raw = query_notebooklm(q)
    libro_idx = raw.upper().find('\nLIBRO:')
    return jsonify({
        "raw_repr": repr(raw[:500]),
        "libro_idx": libro_idx,
        "parsed": parse_response(raw)
    })


@app.route('/api/ask', methods=['POST'])
def ask():
    data = request.get_json()
    if not data or not data.get('question'):
        return jsonify({"error": "Se requiere el campo 'question'"}), 400

    question = data['question'].strip()
    if len(question) > 2000:
        return jsonify({"error": "La pregunta es demasiado larga"}), 400

    try:
        raw = query_notebooklm(question)
        response = parse_response(raw)

        if not response['citations']:
            # Si no se pudo parsear, devolver el texto crudo como intro
            response['intro'] = raw[:800] if raw else "Consulta procesada. Verifica la conexión con NotebookLM."
            response['citations'] = []

        return jsonify(response)

    except subprocess.TimeoutExpired:
        return jsonify({"error": "La consulta tardó demasiado. Intenta de nuevo."}), 504
    except Exception as e:
        return jsonify({"error": f"Error interno: {str(e)}"}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "version": "2", "notebook": NOTEBOOK_URL})


if __name__ == '__main__':
    print("=" * 60)
    print("  Sabiduría de los Libros Sagrados — Backend")
    print("  http://localhost:5000")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5001, debug=False)
