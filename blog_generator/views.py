from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import json
import yt_dlp
import os
import assemblyai as aai
import openai
import re
from .models import BlogPost
import unicodedata
from dotenv import load_dotenv
load_dotenv()

aai.settings.api_key = os.getenv("aai_api_key")
openai.api_key = os.getenv("openai_api_key")

@login_required
def index(request):
    return render(request, 'index.html')

@csrf_exempt
def generate_blog(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            yt_link = data.get('link')
            if not yt_link:
                return JsonResponse({'error': 'No YouTube link provided'}, status=400)

            title = yt_title(yt_link)
            transcription = get_transcription(yt_link)

            if not transcription or "Error" in transcription:
                return JsonResponse({'error': "Failed to get transcript"}, status=500)

            blog_content = generate_blog_from_transcription(transcription)
            if not blog_content:
                return JsonResponse({'error': "Failed to generate blog article"}, status=500)

            new_blog_article = BlogPost.objects.create(
                user=request.user,
                youtube_title=title,
                youtube_link=yt_link,
                generated_content=blog_content,
            )
            new_blog_article.save()

            return JsonResponse({'content': blog_content})
        except Exception as e:
            print(f"Error in generate_blog: {e}")  # Debugging
            return JsonResponse({'error': f"Internal Server Error: {str(e)}"}, status=500)

    return JsonResponse({'error': 'Invalid request method'}, status=405)

def sanitize_filename(filename):
    """
    Remove invalid characters for Windows filenames and normalize Unicode characters.
    """
    filename = unicodedata.normalize('NFKC', filename)
    return re.sub(r'[<>:"/\\|?*\uFF5C]', "_", filename)  # Replacing invalid characters


def yt_title(link):
    """Fetch YouTube video title."""
    ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True}

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info_dict = ydl.extract_info(link, download=False)
            return sanitize_filename(info_dict.get('title', 'Untitled Video'))
        except Exception:
            return "Error retrieving title"

def download_audio(link):
    """Download YouTube audio and return path."""
    output_path = "downloads"
    os.makedirs(output_path, exist_ok=True)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{output_path}/%(id)s.%(ext)s',  # Use ID instead of title
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(link, download=True)
        video_id = info_dict['id']
        raw_audio_path = os.path.join(output_path, f"{video_id}.mp3")

        return raw_audio_path  # No renaming needed, ID is safe


def get_transcription(link):
    """Get transcription using AssemblyAI."""
    try:
        audio_file = download_audio(link)
        if not audio_file or not os.path.exists(audio_file):
            return "Error: Audio file not found."

        transcriber = aai.Transcriber()
        transcript = transcriber.transcribe(audio_file)

        return transcript.text if transcript else "Error: Transcription failed."
    except Exception as e:
        print(f"Error in transcription: {e}")
        return f"Error: {str(e)}"

def generate_blog_from_transcription(transcription):
    """Generate blog article using OpenAI GPT-4."""
    try:
        client = openai.OpenAI(api_key=os.getenv("openai_api_key"))

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a professional blog writer."},
                {"role": "user", "content": f"Write a blog article based on this transcript:\n\n{transcription}"}
            ],
            max_tokens=1000
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        print(f"Error in OpenAI request: {e}")
        return f"Error: {str(e)}"

def blog_list(request):
    blog_articles = BlogPost.objects.filter(user=request.user)
    return render(request, "all-blogs.html", {'blog_articles': blog_articles})

def blog_details(request, pk):
    blog_article_detail = BlogPost.objects.get(id=pk)
    if request.user == blog_article_detail.user:
        return render(request, 'blog-details.html', {'blog_article_detail': blog_article_detail})
    return redirect('/')

def user_login(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect('/')
        return render(request, 'login.html', {'error_message': "Invalid username or password"})

    return render(request, 'login.html')

def user_signup(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        repeatPassword = request.POST.get('repeatPassword')

        if password == repeatPassword:
            try:
                user = User.objects.create_user(username, email, password)
                login(request, user)
                return redirect('/')
            except Exception as e:
                print(f"Signup Error: {e}")
                return render(request, 'signup.html', {'error_message': 'Error creating account'})
        return render(request, 'signup.html', {'error_message': 'Passwords do not match'})

    return render(request, 'signup.html')

def user_logout(request):
    logout(request)
    return redirect('/')
