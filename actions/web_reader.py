import urllib.request
import urllib.parse
from html.parser import HTMLParser

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.hide_content = False

    def handle_starttag(self, tag, attrs):
        if tag in ['script', 'style', 'head', 'title', 'meta', 'noscript', 'header', 'footer', 'nav']:
            self.hide_content = True

    def handle_endtag(self, tag):
        if tag in ['script', 'style', 'head', 'title', 'meta', 'noscript', 'header', 'footer', 'nav']:
            self.hide_content = False

    def handle_data(self, data):
        if not self.hide_content:
            clean = data.strip()
            if clean:
                self.text.append(clean)

def read_web_page(url: str) -> str:
    """Belirtilen URL'ye gider ve sayfa içindeki temiz metni (makaleyi) okur."""
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
        
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode('utf-8', errors='ignore')
            parser = TextExtractor()
            parser.feed(html)
            text = '\n'.join(parser.text)
            
            if len(text) > 6000:
                text = text[:6000] + "\n\n... (Metnin geri kalanı uzunluk sınırı nedeniyle kırpıldı.)"
            return text
    except Exception as e:
        return f"Sayfa okunamadı. Hata: {str(e)}"

def search_web(query: str) -> str:
    """DuckDuckGo Lite üzerinden arama yapar ve ilk 3 sonucu linkleriyle döndürür."""
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
    
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            import re
            results = []
            blocks = html.split('class="result__snippet')[1:]
            for block in blocks[:3]:
                link_match = re.search(r'href="([^"]+)"', block)
                if link_match:
                    link = link_match.group(1)
                    if link.startswith('//duckduckgo.com/l/?uddg='):
                        link = urllib.parse.unquote(link.split('uddg=')[1].split('&')[0])
                    results.append(link)
            
            if not results:
                return "Arama sonucu bulunamadı."
            
            res_str = "Arama Sonuçları (Sitelere girmek için read_web_page kullan):\n"
            for i, r in enumerate(results, 1):
                res_str += f"{i}. {r}\n"
            return res_str
    except Exception as e:
        return f"Arama yapılamadı. Hata: {str(e)}"
