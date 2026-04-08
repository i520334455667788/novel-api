from flask import Flask, request, jsonify
from flask_cors import CORS
import urllib.request
import urllib.error
import urllib.parse
from bs4 import BeautifulSoup
import re
import chardet 

app = Flask(__name__)
CORS(app)

def fetch_html(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
    })
    
    try:
        response = urllib.request.urlopen(req, timeout=15)
        raw_data = response.read()
    except urllib.error.HTTPError as e:
        raise Exception(f"HTTP 錯誤: {e.code} (目標網站可能阻擋了抓取，或網址已失效)")
    except urllib.error.URLError as e:
        raise Exception(f"連線失敗: {e.reason}")
    except Exception as e:
        raise Exception(f"未知的連線錯誤: {str(e)}")
        
    detected = chardet.detect(raw_data)
    encoding = detected['encoding'] if detected['encoding'] else 'utf-8'
    
    if encoding and encoding.lower() in ['gb2312', 'gbk', 'gb18030']:
        encoding = 'gb18030' 
    elif encoding and 'big5' in encoding.lower():
        encoding = 'big5hkscs'
        
    try:
        return raw_data.decode(encoding, errors='replace')
    except:
        return raw_data.decode('utf-8', errors='ignore')

@app.route('/api/status', methods=['GET'])
def status():
    return jsonify({"status": "running", "message": "Vercel API 連線成功！(V4 抗封鎖版)"})

@app.route('/api/search', methods=['GET'])
def search_novel():
    keyword = request.args.get('q', '')
    if not keyword: return jsonify({"error": "請提供關鍵字"}), 400
    
    query = f"{keyword} 小说 目录 笔趣阁"
    search_engines = [
        {"url": f"https://www.bing.com/search?q={urllib.parse.quote(query)}", "type": "bing"},
        {"url": f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}", "type": "ddg"}
    ]
    
    results = []
    last_error = ""
    
    for engine in search_engines:
        try:
            html = fetch_html(engine["url"])
            soup = BeautifulSoup(html, 'html.parser')
            
            if engine["type"] == "bing":
                for li in soup.select('li.b_algo'):
                    a = li.select_first('h2 a')
                    if a and a.get('href') and 'http' in a['href']:
                        if 'baidu.com' not in a['href'] and 'wikipedia.org' not in a['href']:
                            results.append({
                                "title": a.text.replace('\ue000', '').replace('\ue001', '').strip(),
                                "url": a['href'],
                                "source": urllib.parse.urlparse(a['href']).netloc
                            })
            elif engine["type"] == "ddg":
                for a in soup.select('.result__a'):
                    href = a.get('href', '')
                    if 'uddg=' in href:
                        href = urllib.parse.unquote(href.split('uddg=')[1].split('&')[0])
                    if href.startswith('http') and 'baidu.com' not in href:
                        results.append({
                            "title": a.text.strip(),
                            "url": href,
                            "source": urllib.parse.urlparse(href).netloc
                        })
            if len(results) > 0: break 
        except Exception as e:
            last_error = str(e)
            continue
            
    if len(results) > 0:
        unique_results = {r['url']: r for r in results}.values()
        return jsonify({"success": True, "data": list(unique_results)[:15]})
    else:
        return jsonify({"error": f"搜尋失敗: {last_error}"}), 500

@app.route('/api/toc', methods=['GET'])
def get_toc():
    url = request.args.get('url')
    try:
        html = fetch_html(url)
        soup = BeautifulSoup(html, 'html.parser')
        chapters = []
        seen = set()
        
        for a in soup.find_all('a', href=True):
            text = a.text.strip()
            if re.search(r'(第[零一二三四五六七八九十百千万亿0-9]+[章回节折篇]|^\d+\s*$|^\d+\.|^Chapter)', text, re.I):
                abs_url = urllib.parse.urljoin(url, a['href'])
                if abs_url not in seen:
                    seen.add(abs_url)
                    chapters.append({"title": text, "url": abs_url})
        
        if len(chapters) < 5:
            chapters = []
            seen = set()
            for div in soup.find_all(['div', 'dl'], class_=re.compile(r'list|ml|chapter')):
                for a in div.find_all('a', href=True):
                    text = a.text.strip()
                    if text:
                        abs_url = urllib.parse.urljoin(url, a['href'])
                        if abs_url not in seen:
                            seen.add(abs_url)
                            chapters.append({"title": text, "url": abs_url})
                            
        if len(chapters) == 0:
            return jsonify({"error": "解析失敗：無法在此網頁找到章節列表，可能是防爬蟲或是非小說目錄頁"}), 500
            
        return jsonify({"success": True, "data": chapters})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/content', methods=['GET'])
def get_content():
    url = request.args.get('url')
    try:
        html = fetch_html(url)
        soup = BeautifulSoup(html, 'html.parser')
        
        for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'a', 'h1']):
            tag.decompose()
            
        best_div = None
        max_len = 0
        for div in soup.find_all(['div', 'article', 'main', '#content', '#BookText', '.content', '.read_chapterDetail']):
            text = div.get_text()
            if len(text) > max_len and len(text) > 150:
                max_len = len(text)
                best_div = div
                
        if best_div:
            content = str(best_div)
            content = re.sub(r'<br\s*/?>', '\n', content)
            content = re.sub(r'</p>', '\n', content)
            content = re.sub(r'<[^>]+>', '', content).replace('&nbsp;', ' ')
            
            clean_text = re.sub(r'\n\s*\n', '\n\n', content).strip()
            return jsonify({"success": True, "data": clean_text})
            
        return jsonify({"error": "找不到正文內容"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
