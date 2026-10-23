import io
import re
import sqlite3
from datetime import datetime
from collections import Counter

import streamlit as st

try:
    import speech_recognition as sr
except Exception:
    sr = None

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

APP_TITLE = "SpeakWise — AI Communication Skills Analyzer"
DB_PATH = "communication_history.db"

st.set_page_config(page_title=APP_TITLE, page_icon="🎙️", layout="wide")

# ---------- Styling ----------
st.markdown("""
<style>
    .stApp { background: #0b1020; color: #eef2ff; }
    [data-testid="stSidebar"] { background: #11182b; }
    .hero { padding: 1.25rem 1.5rem; border-radius: 18px; background: linear-gradient(120deg,#172554,#312e81); border: 1px solid #334155; margin-bottom: 1rem; }
    .hero h1 { margin-bottom: .25rem; color: white; }
    .hero p { color: #dbeafe; margin-bottom: 0; }
    .small-note { color: #aab6d3; font-size: .88rem; }
    div[data-testid="stMetric"] { background: #121b30; border: 1px solid #273653; padding: 12px; border-radius: 12px; }
    .stButton>button { border-radius: 10px; }
</style>
""", unsafe_allow_html=True)

# ---------- Persistence ----------
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                mode TEXT NOT NULL,
                question TEXT,
                word_count INTEGER,
                wpm REAL,
                filler_count INTEGER,
                overall_score REAL,
                transcript TEXT
            )
        """)
        conn.commit()

def save_attempt(mode, question, analysis, transcript):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO attempts
            (created_at, mode, question, word_count, wpm, filler_count, overall_score, transcript)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now().isoformat(timespec="seconds"), mode, question,
             analysis["word_count"], analysis["wpm"], analysis["filler_total"],
             analysis["overall_score"], transcript)
        )
        conn.commit()

def load_attempts():
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            """SELECT created_at, mode, question, word_count, wpm, filler_count, overall_score
               FROM attempts ORDER BY id DESC LIMIT 100"""
        ).fetchall()

init_db()

# ---------- Analysis helpers ----------
FILLERS = [
    "um", "uh", "erm", "hmm", "you know", "i mean", "sort of", "kind of",
    "basically", "actually", "literally", "right", "okay"
]
STOPWORDS = set("""
a an the and or but if then so because as of at by for from in into on onto to with
is am are was were be been being have has had do does did can could would should
will may might must i me my mine we us our ours you your yours he she it they them
their this that these those there here who what when where why how which while
""".split())

INTERVIEW_QUESTIONS = {
    "Tell me about yourself.": "intro",
    "Why should we select you?": "strengths",
    "What is your greatest strength?": "strengths",
    "What is one area you are improving?": "reflection",
    "Describe a challenge you faced and how you handled it.": "star",
    "Tell me about a time you worked in a team.": "star",
    "Describe a mistake and what you learned from it.": "star",
    "Why are you interested in this role?": "motivation",
    "Explain a project you worked on.": "project",
    "Give a one-minute opinion on a topic you care about.": "general",
}

def clean_words(text):
    return re.findall(r"\b[\w'-]+\b", text.lower())

def sentence_list(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text.strip()) if s.strip()]

def count_fillers(text):
    lower = text.lower()
    found = {}
    for phrase in FILLERS:
        pattern = r"(?<!\w)" + re.escape(phrase) + r"(?!\w)"
        count = len(re.findall(pattern, lower))
        # These terms are often meaningful words, so they are reported as possible fillers.
        if count:
            found[phrase] = count
    return found

def grammar_checks(text):
    """Transparent lightweight checks, not a full grammar engine."""
    findings = []
    rules = [
        (r"\b(i)\s+am\s+agree\b", "I agree", "Use “I agree,” not “I am agree.”"),
        (r"\b(he|she|it)\s+don't\b", None, "With he/she/it, use “doesn't” instead of “don't.”"),
        (r"\b(he|she|it)\s+have\b", None, "With he/she/it, “has” is usually correct instead of “have.”"),
        (r"\b(your)\s+welcome\b", "you're welcome", "Use “you're welcome” when responding to thanks."),
        (r"\b(more better|most easiest|more easier)\b", None, "Avoid double comparatives; use “better” or “easier.”"),
        (r"\b(i)\s+is\b", "I am", "Use “I am” with the subject “I.”"),
        (r"\b(we was|they was|you was)\b", None, "Use “were” with we, they, and you."),
        (r"\b(a)\s+(hour|honest|honour|heir)\b", None, "These words begin with a vowel sound, so “an” is usually used."),
        (r"\b(an)\s+(university|unicorn|user|European)\b", None, "These words begin with a consonant sound, so “a” is usually used."),
    ]
    lower = text.lower()
    for pattern, replacement, explanation in rules:
        matches = list(re.finditer(pattern, lower, flags=re.IGNORECASE))
        for m in matches:
            original = text[m.start():m.end()]
            suggestion = replacement or "Review this phrase"
            findings.append({"original": original, "suggestion": suggestion, "explanation": explanation})
    if text and not re.search(r"[.!?]\s*$", text.strip()):
        findings.append({"original": text.strip()[-45:], "suggestion": "Add appropriate punctuation", "explanation": "A complete response usually benefits from clear sentence punctuation."})
    return findings[:12]

def vocabulary_analysis(words):
    meaningful = [w for w in words if w not in STOPWORDS and len(w) > 2 and w.isalpha()]
    unique = set(meaningful)
    diversity = (len(unique) / len(meaningful) * 100) if meaningful else 0
    counts = Counter(meaningful)
    repeated = [(w, c) for w, c in counts.most_common(8) if c >= 3]
    return diversity, repeated, len(unique)

def analyse_transcript(text, duration_seconds, question, mode):
    words = clean_words(text)
    sentences = sentence_list(text)
    fillers = count_fillers(text)
    filler_total = sum(fillers.values())
    word_count = len(words)
    wpm = (word_count / duration_seconds * 60) if duration_seconds and duration_seconds > 0 else None
    avg_sentence = word_count / len(sentences) if sentences else 0
    diversity, repeated, unique_vocab = vocabulary_analysis(words)
    grammar = grammar_checks(text)

    recommendations = []
    if word_count < 25:
        recommendations.append("Your answer is quite short. Add a relevant explanation or specific example if the question calls for one.")
    if word_count > 220:
        recommendations.append("Your answer is long. Try removing repeated points and keeping each sentence focused.")
    if wpm is not None and wpm < 100:
        recommendations.append("Your speaking pace is on the slow side. Check whether long pauses are intentional and practise connecting ideas.")
    elif wpm is not None and wpm > 170:
        recommendations.append("Your speaking pace may be fast. Pause at sentence boundaries and articulate key points clearly.")
    if filler_total >= 5:
        recommendations.append(f"You used {filler_total} possible filler expressions. Practise a short silent pause instead of filling every gap.")
    elif filler_total > 0:
        recommendations.append("Review the highlighted possible filler expressions. Words such as “like” and “actually” may be meaningful in context.")
    if len(grammar) > 0:
        recommendations.append("Review the grammar suggestions and decide which apply to your intended meaning.")
    if len(sentences) >= 2 and avg_sentence > 28:
        recommendations.append("Some sentences may be long. Split complex thoughts into shorter sentences.")
    if diversity < 45 and len(words) >= 40:
        recommendations.append("Try using precise, relevant words rather than repeating the same general expressions.")
    if not recommendations:
        recommendations.append("Keep practising. Focus on answering the question directly, supporting your points, and ending with a clear takeaway.")

    # Simple heuristic sub-scores. These are coaching indicators, not validated proficiency scores.
    pace_score = 75 if wpm is None else max(35, min(100, 100 - abs(wpm - 135) * 0.65))
    filler_score = max(25, 100 - filler_total * 7)
    grammar_score = max(40, 100 - len(grammar) * 8)
    structure_score = 55
    if word_count >= 45: structure_score += 10
    if len(sentences) >= 3: structure_score += 10
    if re.search(r"\b(for example|for instance|because|as a result|therefore|first|finally|in conclusion)\b", text, re.I):
        structure_score += 10
    if question and question in INTERVIEW_QUESTIONS and INTERVIEW_QUESTIONS[question] == "star":
        for term in ["situation", "task", "action", "result"]:
            if re.search(r"\b" + term + r"\b", text, re.I):
                structure_score += 2
    structure_score = min(100, structure_score)
    vocabulary_score = min(100, max(40, diversity + 30)) if word_count >= 15 else 55
    overall = round((pace_score * 0.20 + filler_score * 0.15 + grammar_score * 0.25 +
                     structure_score * 0.25 + vocabulary_score * 0.15), 1)
    return {
        "word_count": word_count, "sentence_count": len(sentences), "wpm": round(wpm, 1) if wpm is not None else None,
        "duration": duration_seconds, "fillers": fillers, "filler_total": filler_total,
        "avg_sentence": round(avg_sentence, 1), "vocab_diversity": round(diversity, 1),
        "unique_vocab": unique_vocab, "repeated_words": repeated, "grammar": grammar,
        "recommendations": recommendations, "pace_score": round(pace_score),
        "filler_score": round(filler_score), "grammar_score": round(grammar_score),
        "structure_score": round(structure_score), "vocabulary_score": round(vocabulary_score),
        "overall_score": overall, "sentences": sentences
    }

def transcribe_audio(uploaded_file):
    if sr is None:
        return None, "SpeechRecognition is not installed. Install requirements.txt and try again."
    name = uploaded_file.name.lower()
    if not name.endswith((".wav", ".aiff", ".aif", ".flac")):
        return None, "This starter transcription flow accepts WAV, AIFF, or FLAC files. Convert MP3/M4A to WAV first, or enter the transcript manually."
    try:
        recognizer = sr.Recognizer()
        audio = sr.AudioFile(io.BytesIO(uploaded_file.getvalue()))
        with audio as source:
            data = recognizer.record(source)
        text = recognizer.recognize_google(data)
        return text, None
    except sr.UnknownValueError:
        return None, "Speech could not be understood clearly. Try a clearer recording or edit the transcript manually."
    except sr.RequestError as exc:
        return None, f"Speech recognition service is unavailable or internet access failed: {exc}"
    except Exception as exc:
        return None, f"Could not process this audio file: {exc}"

def create_pdf(transcript, question, analysis, mode):
    if not REPORTLAB_AVAILABLE:
        return None
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=0.65*inch, leftMargin=0.65*inch,
                            topMargin=0.65*inch, bottomMargin=0.65*inch)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SubtitleCustom", parent=styles["Normal"], textColor=colors.HexColor("#475569"), spaceAfter=12))
    styles.add(ParagraphStyle(name="SectionCustom", parent=styles["Heading2"], textColor=colors.HexColor("#243b75"), spaceBefore=12, spaceAfter=6))
    story = [
        Paragraph("SpeakWise Communication Assessment", styles["Title"]),
        Paragraph(f"Generated {datetime.now().strftime('%d %B %Y, %H:%M')} · Input: {mode}", styles["SubtitleCustom"]),
        Paragraph("Important: Scores are heuristic coaching indicators, not a validated language, hiring, or psychological assessment.", styles["Italic"]),
        Spacer(1, 10),
        Paragraph("Assessment summary", styles["SectionCustom"]),
    ]
    metrics = [
        ["Metric", "Result"],
        ["Overall coaching score", f"{analysis['overall_score']}/100"],
        ["Words / sentences", f"{analysis['word_count']} / {analysis['sentence_count']}"],
        ["Speaking speed", f"{analysis['wpm']} WPM" if analysis["wpm"] is not None else "Not available (duration not provided)"],
        ["Possible filler expressions", str(analysis["filler_total"])],
        ["Vocabulary diversity", f"{analysis['vocab_diversity']}%"],
    ]
    table = Table(metrics, colWidths=[2.7*inch, 3.5*inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#243b75")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("GRID", (0,0), (-1,-1), .4, colors.HexColor("#cbd5e1")),
        ("BACKGROUND", (0,1), (-1,-1), colors.HexColor("#f8fafc")),
        ("PADDING", (0,0), (-1,-1), 7),
    ]))
    story.append(table)
    if question:
        story += [Paragraph("Practice question", styles["SectionCustom"]), Paragraph(question.replace("&", "&amp;"), styles["BodyText"])]
    story += [Paragraph("Dimension scores", styles["SectionCustom"])]
    dim_data = [["Dimension", "Score / 100"],
                ["Speaking pace", str(analysis["pace_score"])],
                ["Filler-word control", str(analysis["filler_score"])],
                ["Grammar checks", str(analysis["grammar_score"])],
                ["Answer structure", str(analysis["structure_score"])],
                ["Vocabulary indicator", str(analysis["vocabulary_score"])]]
    dim_table = Table(dim_data, colWidths=[3.5*inch, 2.7*inch])
    dim_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#243b75")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("GRID", (0,0), (-1,-1), .4, colors.HexColor("#cbd5e1")),
        ("PADDING", (0,0), (-1,-1), 7),
    ]))
    story.append(dim_table)
    story.append(Paragraph("Recommended next steps", styles["SectionCustom"]))
    for rec in analysis["recommendations"]:
        story.append(Paragraph("• " + rec.replace("&", "&amp;"), styles["BodyText"]))
        story.append(Spacer(1, 4))
    if analysis["fillers"]:
        story.append(Paragraph("Possible filler expressions", styles["SectionCustom"]))
        story.append(Paragraph(", ".join(f"{k}: {v}" for k, v in analysis["fillers"].items()), styles["BodyText"]))
    if analysis["grammar"]:
        story.append(Paragraph("Grammar review", styles["SectionCustom"]))
        for item in analysis["grammar"]:
            story.append(Paragraph(f"<b>Original:</b> {item['original']}<br/><b>Suggestion:</b> {item['suggestion']}<br/>{item['explanation']}", styles["BodyText"]))
            story.append(Spacer(1, 6))
    story.append(Paragraph("Transcript", styles["SectionCustom"]))
    safe_text = (transcript.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                 .replace("\n", "<br/>"))
    story.append(Paragraph(safe_text or "No transcript provided.", styles["BodyText"]))
    doc.build(story)
    return buffer.getvalue()

# ---------- Header ----------
st.markdown("""
<div class="hero">
  <h1>🎙️ SpeakWise</h1>
  <p>Practise speaking. Understand your habits. Build clearer communication.</p>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("Your practice session")
    page = st.radio("Navigate", ["Analyse a response", "Interview practice", "Progress history", "About & limitations"])
    st.divider()
    st.caption("Privacy: recordings are processed for the current session and are not saved to the history database. Transcripts are saved only when you click Save attempt.")

if page == "Analyse a response":
    left, right = st.columns([1.2, 0.8])
    with left:
        st.subheader("1. Choose your practice")
        mode = st.selectbox("Practice type", ["General communication", "Job interview", "Presentation", "Academic answer", "Everyday conversation"])
        question_options = ["Custom / no question"] + list(INTERVIEW_QUESTIONS.keys())
        question = st.selectbox("Question or prompt", question_options)
        custom_question = st.text_input("Or enter your own question (optional)")
        if custom_question.strip():
            question = custom_question.strip()
        st.subheader("2. Provide your response")
        input_method = st.radio("Input method", ["Type / paste transcript", "Upload audio"], horizontal=True)
        transcript = ""
        uploaded_audio = None
        if input_method == "Type / paste transcript":
            transcript = st.text_area("Transcript", height=230, placeholder="Paste what you said, or type a response here...")
        else:
            if hasattr(st, "audio_input"):
                recorded_audio = st.audio_input("Record your response")
            else:
                recorded_audio = None
                st.info("Your Streamlit version does not offer in-browser recording. Use the upload option below.")
            uploaded_audio = st.file_uploader("Or upload WAV, AIFF, or FLAC audio", type=["wav", "aiff", "aif", "flac"])
            if recorded_audio is not None:
                uploaded_audio = recorded_audio
                st.audio(recorded_audio)
            elif uploaded_audio is not None:
                st.audio(uploaded_audio)
            if st.button("Transcribe audio"):
                if uploaded_audio is None:
                    st.warning("Record or upload audio first.")
                else:
                    with st.spinner("Transcribing audio..."):
                        converted, error = transcribe_audio(uploaded_audio)
                    if error:
                        st.error(error)
                    else:
                        st.session_state["transcribed_text"] = converted
                        st.success("Transcription completed. Review it before analysis.")
            transcript = st.text_area("Review / edit transcript", value=st.session_state.get("transcribed_text", ""), height=180,
                                      help="Check transcription errors before analysing. Transcription quality affects the results.")
        duration = st.number_input("Actual speaking duration (seconds)", min_value=0, max_value=7200, value=0, step=5,
                                   help="Enter the recording duration to calculate words per minute. Do not guess if you can check the recording.")
        run_analysis = st.button("✨ Analyse my communication", type="primary", use_container_width=True)

    with right:
        st.subheader("What you'll receive")
        st.markdown("""
        - Speaking statistics and pace estimate
        - Possible filler expressions
        - Repeated vocabulary indicators
        - Basic grammar checks and suggestions
        - Answer-structure coaching
        - Personalised practice recommendations
        - Downloadable PDF report
        """)
        st.info("For best results, use a transcript you have reviewed and provide the actual speaking duration.")

    if run_analysis:
        if not transcript.strip():
            st.warning("Enter a transcript or transcribe an audio recording first.")
        else:
            actual_question = "" if question == "Custom / no question" else question
            analysis = analyse_transcript(transcript, duration, actual_question, mode)
            st.session_state["last_analysis"] = analysis
            st.session_state["last_transcript"] = transcript
            st.session_state["last_question"] = actual_question
            st.session_state["last_mode"] = mode

    if "last_analysis" in st.session_state:
        a = st.session_state["last_analysis"]
        t = st.session_state["last_transcript"]
        q = st.session_state.get("last_question", "")
        m = st.session_state.get("last_mode", mode)
        st.divider()
        st.subheader("Your communication dashboard")
        st.caption("These are heuristic coaching indicators. They are not validated scores of intelligence, personality, hiring suitability, or English proficiency.")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Overall coaching score", f"{a['overall_score']}/100")
        c2.metric("Words", a["word_count"])
        c3.metric("Possible fillers", a["filler_total"])
        c4.metric("Speaking speed", f"{a['wpm']} WPM" if a["wpm"] is not None else "N/A")
        st.subheader("Dimension indicators")
        score_cols = st.columns(5)
        dimensions = [
            ("Pace", a["pace_score"]), ("Filler control", a["filler_score"]),
            ("Grammar checks", a["grammar_score"]), ("Structure", a["structure_score"]),
            ("Vocabulary", a["vocabulary_score"])
        ]
        for col, (label, score) in zip(score_cols, dimensions):
            col.metric(label, f"{score}/100")
        st.progress(min(100, int(a["overall_score"])) / 100)
        st.subheader("Speaking and text statistics")
        x1, x2, x3, x4 = st.columns(4)
        x1.metric("Sentences", a["sentence_count"])
        x2.metric("Average words / sentence", a["avg_sentence"])
        x3.metric("Vocabulary diversity", f"{a['vocab_diversity']}%")
        x4.metric("Unique vocabulary", a["unique_vocab"])
        tab1, tab2, tab3, tab4 = st.tabs(["Recommendations", "Filler expressions", "Grammar review", "Transcript"])
        with tab1:
            for rec in a["recommendations"]:
                st.markdown(f"- {rec}")
            if q:
                st.markdown("#### Question relevance checklist")
                st.write("Question:", q)
                st.write("Use your judgement to confirm that the response directly answers the question. This prototype does not yet use a semantic AI model to reliably score relevance.")
        with tab2:
            if a["fillers"]:
                st.write("Possible filler expressions found:")
                st.dataframe([{"Expression": k, "Count": v} for k, v in a["fillers"].items()], use_container_width=True, hide_index=True)
                st.caption("Some words (for example, “like”, “right”, “actually”) can be meaningful. Review context instead of treating every occurrence as a mistake.")
            else:
                st.success("No listed possible filler expressions were detected.")
        with tab3:
            if a["grammar"]:
                st.dataframe([{"Text to review": x["original"], "Suggestion": x["suggestion"], "Why": x["explanation"]} for x in a["grammar"]], use_container_width=True, hide_index=True)
                st.caption("This is a small rule-based check, not comprehensive grammar correction.")
            else:
                st.success("No issues were caught by the basic grammar rules. This does not guarantee that the text is error-free.")
            if a["repeated_words"]:
                st.markdown("**Frequently repeated content words**")
                st.write(", ".join(f"{word} ({count})" for word, count in a["repeated_words"]))
        with tab4:
            st.write(t)
        action1, action2 = st.columns(2)
        with action1:
            if st.button("Save attempt to progress history"):
                save_attempt(m, q, a, t)
                st.success("Attempt saved locally.")
        with action2:
            pdf_data = create_pdf(t, q, a, m)
            if pdf_data:
                st.download_button("Download assessment PDF", data=pdf_data,
                                   file_name=f"speakwise_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                                   mime="application/pdf", use_container_width=True)
            else:
                st.warning("Install reportlab to enable PDF reports.")

elif page == "Interview practice":
    st.subheader("Interview practice")
    st.write("Choose a question, prepare an answer, and analyse it on the Analyse a response page.")
    selected = st.selectbox("Choose an interview question", list(INTERVIEW_QUESTIONS.keys()))
    st.markdown(f"### {selected}")
    if INTERVIEW_QUESTIONS[selected] == "star":
        st.info("Try STAR: Situation → Task → Action → Result. Use concrete details and explain the outcome.")
    elif INTERVIEW_QUESTIONS[selected] == "intro":
        st.info("Try: present situation → relevant experience or strengths → why you are here.")
    elif INTERVIEW_QUESTIONS[selected] == "project":
        st.info("Try: problem → your role → approach → result → what you learned.")
    else:
        st.info("Answer directly, give a specific example where useful, and finish with a clear takeaway.")
    st.write("Go to **Analyse a response** and select the same question to receive the available coaching indicators.")

elif page == "Progress history":
    st.subheader("Progress history")
    rows = load_attempts()
    if not rows:
        st.info("No saved attempts yet. Analyse a response and click “Save attempt to progress history”.")
    else:
        st.dataframe([{
            "Date": r[0], "Practice type": r[1], "Question": r[2],
            "Words": r[3], "WPM": r[4], "Possible fillers": r[5], "Score": r[6]
        } for r in rows], use_container_width=True, hide_index=True)
        if len(rows) >= 2:
            latest = rows[0][6]
            previous = rows[1][6]
            change = round(latest - previous, 1)
            st.metric("Change from previous saved attempt", f"{change:+.1f} points")
        st.caption("History is stored in a local SQLite database on the machine or server running this app. On some hosted deployments, local files may not persist permanently.")
        if st.button("Delete all local progress history"):
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("DELETE FROM attempts")
                conn.commit()
            st.success("Local progress history deleted.")
            st.rerun()

else:
    st.subheader("About SpeakWise")
    st.write("SpeakWise is a learning prototype designed to help users reflect on speech and communication habits.")
    st.markdown("""
    **Current capabilities**
    - Text-based word and sentence statistics.
    - Rule-based detection of a limited set of possible filler expressions.
    - A small set of basic grammar checks.
    - Approximate speaking-rate calculation when the user provides the real duration.
    - Interview prompts, local progress history, and PDF export.

    **Current limitations**
    - The overall and dimension scores use transparent heuristics and are not scientifically validated.
    - Grammar checks are limited and can miss errors or flag context-dependent phrasing.
    - Speech transcription uses an online recognition service and requires internet access.
    - Transcription supports WAV, AIFF, and FLAC in this version. MP3/M4A conversion is not included.
    - This version does not yet provide validated pronunciation scoring, emotion detection, facial analysis, or reliable semantic scoring of answer relevance.
    - No communication score should be used for hiring, diagnosis, or high-stakes decisions.
    - Do not upload private or confidential recordings. Obtain consent before analysing another person's voice.
    """)
    st.markdown("**Recommended next upgrades:** optional AI-powered grammar and semantic feedback, robust audio conversion, validated pronunciation assessment, multilingual support, authentication, and durable cloud storage.")
