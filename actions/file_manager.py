import os
import shutil

def list_directory(path: str) -> str:
    """Belirtilen klasördeki dosya ve klasörleri listeler."""
    try:
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            return f"Hata: {path} bulunamadı."
        
        items = os.listdir(path)
        if not items:
            return f"{path} klasörü boş."
            
        dirs = [d for d in items if os.path.isdir(os.path.join(path, d))]
        files = [f for f in items if os.path.isfile(os.path.join(path, f))]
        
        res = f"--- {path} İçeriği ---\n"
        res += f"KLASÖRLER ({len(dirs)}): " + ", ".join(dirs) + "\n"
        res += f"DOSYALAR ({len(files)}): " + ", ".join(files) + "\n"
        return res
    except Exception as e:
        return f"Klasör okuma hatası: {str(e)}"

def read_file_content(path: str) -> str:
    """Belirtilen dosyanın metin içeriğini okur."""
    try:
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            return f"Hata: {path} bulunamadı."
        
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
            if len(text) > 4000:
                text = text[:4000] + "\n... (İçerik çok uzun, kırpıldı)"
            return text
    except Exception as e:
        return f"Dosya okuma hatası: {str(e)}"

def manage_file(action: str, source: str, destination: str = "") -> str:
    """Dosya taşıma, kopyalama veya silme işlemleri yapar. (action: 'copy', 'move', 'delete')"""
    try:
        source = os.path.expanduser(source)
        if destination:
            destination = os.path.expanduser(destination)
            
        if not os.path.exists(source):
            return f"Hata: Kaynak {source} bulunamadı."
            
        if action == "copy":
            if os.path.isdir(source):
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
            return f"Kopyalandı: {source} -> {destination}"
            
        elif action == "move":
            shutil.move(source, destination)
            return f"Taşındı: {source} -> {destination}"
            
        elif action == "delete":
            if os.path.isdir(source):
                shutil.rmtree(source)
            else:
                os.remove(source)
            return f"Silindi: {source}"
            
        return f"Bilinmeyen eylem: {action}"
    except Exception as e:
        return f"Dosya işlem hatası: {str(e)}"
