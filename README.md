# SpeakWise — AI Communication Skills Analyzer

A Streamlit learning prototype for analysing speech transcripts and practising communication.

## Features included
- Transcript entry and WAV/AIFF/FLAC audio upload
- Browser audio recording where supported by the installed Streamlit version
- Online speech transcription using SpeechRecognition's Google recognition option
- Word count, sentence count, vocabulary diversity, possible filler expressions, repeated content words
- A small set of basic grammar checks
- Heuristic coaching indicators and actionable suggestions
- Interview question prompts, including STAR guidance
- Downloadable PDF assessment report
- Local SQLite history for saved attempts

## Requirements
- Python 3.10 or newer (Python 3.11 is a sensible default)
- Internet connection for online speech transcription

## Run on Windows with VS Code
Open this folder in VS Code, then Terminal > New Terminal.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open the local address shown in the terminal, usually http://localhost:8501.

If PowerShell blocks activation, you can run the environment's Python directly instead:
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

## GitHub upload
Create a GitHub repository, then from this folder:
```bash
git init
git add app.py requirements.txt README.md .gitignore
git commit -m "Build SpeakWise communication analyzer"
git branch -M main
git remote add origin YOUR_REPOSITORY_URL
git push -u origin main
```

## Deployment
Deploy the repository with Streamlit Community Cloud and set the main file path to `app.py`.

## Important limitations
This is a prototype, not a validated assessment instrument. Overall and dimension scores are heuristic indicators. Grammar feedback uses limited rules. Possible filler expressions can be meaningful in context. Transcription requires internet and is not guaranteed to be correct. Pronunciation scoring, facial/emotion analysis, and reliable semantic relevance scoring are not implemented in this version. Do not use results for hiring or other high-stakes decisions. Do not upload confidential recordings.

The SQLite history database is local to the running environment. Hosted environments may not preserve local files permanently.
