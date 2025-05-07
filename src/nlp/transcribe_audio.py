import openai
import os
from dotenv import load_dotenv
import whisper

# Load your OpenAI API key
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

# Initialize Whisper model
whisper_model = whisper.load_model("base")

def transcribe_audio(file_path):
    result = whisper_model.transcribe(file_path)
    return result["text"]

def generate_funny_reply(scammer_text):
    prompt = f"""
    You are playing the role of a very confused, retired CIA field agent in his late 80s. 
    You are being called by a scammer, but you don’t know that — and you're extremely polite but constantly get sidetracked by memories of old missions, Cold War conspiracies, and bizarre classified details. 
    You often ramble about strange events, confuse the scammer with wild anecdotes, and never answer their actual questions.

    Never directly confront the scammer — your only goal is to confuse and waste their time as much as possible.

    Scammer: {scammer_text}
    Retired CIA Agent:
    """

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.95,
        max_tokens=200
    )

    reply = response['choices'][0]['message']['content']
    return reply.strip()

if __name__ == "__main__":
    # Example audio file
    audio_file = "path_to_your_audio_file.wav"  # Replace with actual file path
    transcription = transcribe_audio(audio_file)
    
    print("Scammer Transcript:", transcription)
    response = generate_funny_reply(transcription)
    print("CIA Grandpa Response:", response)
