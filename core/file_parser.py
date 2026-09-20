import os
import mimetypes
import zipfile
import tempfile
import shutil

def parse_file_to_text(filepath: str) -> str:
    """Belirtilen dosyayı okur ve içindeki metni çıkarır."""
    if not os.path.exists(filepath):
        return f"[HATA: Dosya bulunamadı: {filepath}]"
    
    ext = filepath.lower().split('.')[-1]
    
    try:
        # Metin dosyaları
        if ext in ['txt', 'md', 'py', 'js', 'html', 'css', 'json', 'csv', 'xml', 'log']:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
                
        # PDF Dosyaları
        elif ext == 'pdf':
            try:
                import PyPDF2
                text = ""
                with open(filepath, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    for page in reader.pages:
                        text += page.extract_text() + "\n"
                return text
            except ImportError:
                return "[HATA: PDF okumak için 'PyPDF2' modülü gerekli. 'pip install PyPDF2' çalıştırın.]"
                
        # Word Dosyaları
        elif ext in ['doc', 'docx']:
            try:
                import docx
                doc = docx.Document(filepath)
                return "\n".join([p.text for p in doc.paragraphs])
            except ImportError:
                return "[HATA: Word okumak için 'python-docx' modülü gerekli. 'pip install python-docx' çalıştırın.]"
                

        # Resim Dosyaları (Gemini Vision ile analiz edilip metne çevrilir)
        elif ext in ['png', 'jpg', 'jpeg', 'webp', 'bmp']:
            try:
                from google import genai
                from google.genai import types
                from app_config import get_app_config_value
                from pathlib import Path
                
                api_key = str(get_app_config_value("gemini_api_key", "") or "").strip()
                if not api_key:
                    return "[HATA: Resim okumak için Gemini API Anahtarı eksik.]"
                    
                client = genai.Client(api_key=api_key)
                
                # Resmi okuyup Part nesnesine çevirelim
                import mimetypes
                mime_type, _ = mimetypes.guess_type(filepath)
                if not mime_type: mime_type = "image/jpeg"
                
                with open(filepath, "rb") as img_file:
                    img_bytes = img_file.read()
                    
                image_part = types.Part.from_bytes(data=img_bytes, mime_type=mime_type)
                
                prompt = "Kullanıcı bu resmi yükledi. Lütfen bu resimde ne gördüğünü en ince detayına kadar (üzerindeki yazılar, şekiller, objeler, genel bağlam) detaylıca açıkla ki göremeyen bir yapay zeka bu resimde ne olduğunu tamamen anlayabilsin."
                
                response = client.models.generate_content(
                    model="models/gemini-2.5-flash",
                    contents=[types.Part.from_text(text=prompt), image_part],
                )
                
                reply = str(getattr(response, "text", "") or "").strip()
                return f"=== KULLANICININ YÜKLEDİĞİ RESMİN GÖRSEL ANALİZİ ===\n{reply}"
            except Exception as ex:
                return f"[HATA: Resim analiz edilemedi: {str(ex)}]"
                
        # ZIP Dosyaları (İçindeki metin dosyalarını çıkarıp okur)
        elif ext == 'zip':
            text_content = f"--- {os.path.basename(filepath)} (ZIP) İçeriği ---\n\n"
            with tempfile.TemporaryDirectory() as tmpdir:
                with zipfile.ZipFile(filepath, 'r') as zip_ref:
                    zip_ref.extractall(tmpdir)
                    for root, dirs, files in os.walk(tmpdir):
                        for file in files:
                            sub_ext = file.lower().split('.')[-1]
                            if sub_ext in ['txt', 'md', 'py', 'json', 'csv', 'log', 'js', 'html']:
                                sub_path = os.path.join(root, file)
                                with open(sub_path, 'r', encoding='utf-8', errors='ignore') as f:
                                    text_content += f"=== Dosya: {file} ===\n{f.read()}\n\n"
            return text_content
            
        else:
            return f"[BİLGİ: {ext} formatı tam desteklenmiyor. Yalnızca dosya adı iletildi.]"
            
    except Exception as e:
        return f"[HATA: Dosya okunurken hata oluştu: {str(e)}]"
