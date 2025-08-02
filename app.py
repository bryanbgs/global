import os
import re
import time
import threading
import requests
from flask import Flask, Response, request, abort, url_for
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, quote, unquote

app = Flask(__name__)

BASE_URL = "https://streamtpglobal.com/global1.php?stream={}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://streamtpglobal.com/",
    "Origin": "https://streamtpglobal.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
    "Connection": "keep-alive"
}

STREAM_CACHE = {}
CACHE_TTL = 300  # 5 minutos de caché
LOCK = threading.Lock()

def load_channels():
    channels = []
    try:
        with open("canales.txt", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    channels.append(line)
    except FileNotFoundError:
        print("⚠️ canales.txt no encontrado. Creando archivo vacío.")
        open("canales.txt", "w").close()
    return channels

CHANNELS = load_channels()

def extract_m3u8_url(canal, retry=2):
    url = BASE_URL.format(canal)
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        response = session.get(url, timeout=15)
        response.raise_for_status()
        print(f"✅ Acceso exitoso a {url}")

        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Estrategia 1: Buscar en scripts (regex mejorado)
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string:
                # Patrón mejorado para URLs m3u8 con token
                matches = re.findall(
                    r'https?://[^\s\'"\\<>]+\.m3u8\?[^\s\'"\\<>]+', 
                    script.string
                )
                for match in matches:
                    if 'token=' in match:
                        print(f"✅ URL encontrada en script: {match}")
                        return match
        
        # Estrategia 2: Buscar en iframes
        iframes = soup.find_all('iframe')
        for iframe in iframes:
            src = iframe.get('src', '')
            if '.m3u8' in src and 'token=' in src:
                print(f"✅ URL encontrada en iframe: {src}")
                return src
        
        # Estrategia 3: Buscar en elementos video
        video_tags = soup.find_all('video')
        for video in video_tags:
            src = video.get('src', '')
            if '.m3u8' in src and 'token=' in src:
                print(f"✅ URL encontrada en video: {src}")
                return src
        
        # Estrategia 4: Buscar en todo el cuerpo
        body_text = str(soup.body)
        matches = re.findall(
            r'https?://[^\s\'"\\<>]+\.m3u8\?[^\s\'"\\<>]+', 
            body_text
        )
        for match in matches:
            if 'token=' in match:
                print(f"✅ URL encontrada en body: {match}")
                return match
                
        print(f"⚠️ No se encontró URL m3u8 en {url}")

    except requests.exceptions.RequestException as e:
        print(f"❌ Error de conexión para {canal}: {e}")
        if retry > 0:
            print(f"🔄 Reintentando ({retry} intentos restantes)...")
            time.sleep(2)
            return extract_m3u8_url(canal, retry-1)
            
    except Exception as e:
        print(f"❌ Error inesperado para {canal}: {e}")
        
    return None

def rewrite_m3u8(content, base_url, canal):
    """Reescribe TODO el contenido del M3U8 para que todas las URLs pasen por el proxy"""
    lines = content.splitlines()
    rewritten = []
    in_segment = False

    for line in lines:
        stripped = line.strip()
        
        # 1. Líneas de metadatos (EXTINF, etc.)
        if stripped.startswith('#EXTINF:'):
            rewritten.append(line)
            in_segment = True
            continue
            
        # 2. Líneas de segmentos (las que siguen a EXTINF)
        if in_segment and stripped:
            # Asegurar que la URL sea absoluta
            if not stripped.startswith('http'):
                abs_url = urljoin(base_url, stripped)
            else:
                abs_url = stripped
                
            # Codificar la URL para el proxy
            encoded_url = quote(abs_url, safe='')
            proxy_url = url_for('proxy_segment', canal=canal, real_url=encoded_url, _external=True)
            rewritten.append(proxy_url)
            in_segment = False
            continue
            
        # 3. Líneas de claves (EXT-X-KEY)
        if stripped.startswith('#EXT-X-KEY') and 'URI="' in stripped:
            # Extraer y reescribir la URL de la clave
            uri_match = re.search(r'URI="([^"]+)"', stripped)
            if uri_match:
                key_url = uri_match.group(1)
                # Hacer la URL absoluta si es relativa
                if not key_url.startswith('http'):
                    key_url = urljoin(base_url, key_url)
                # Crear URL proxy para la clave
                encoded_key_url = quote(key_url, safe='')
                proxy_key_url = url_for('proxy_segment', canal=canal, real_url=encoded_key_url, _external=True)
                # Reemplazar en la línea
                new_line = stripped.replace(uri_match.group(0), f'URI="{proxy_key_url}"')
                rewritten.append(new_line)
                continue
            else:
                rewritten.append(stripped)
                continue
            
        # 4. Otras líneas (dejarlas igual)
        rewritten.append(line)

    return "\n".join(rewritten)

@app.route('/stream/<canal>.m3u8')
def proxy_playlist(canal):
    if canal not in CHANNELS:
        abort(404, "Canal no encontrado")

    # Obtener o actualizar caché
    cached = STREAM_CACHE.get(canal)
    if not cached or time.time() > cached.get('expires', 0):
        with LOCK:
            print(f"🔍 Actualizando caché para {canal}...")
            m3u8_url = extract_m3u8_url(canal)
            if m3u8_url:
                # Calcular base_url correctamente
                parsed = urlparse(m3u8_url)
                base_url = f"{parsed.scheme}://{parsed.netloc}{os.path.dirname(parsed.path)}/"
                if not base_url.endswith('/'):
                    base_url += '/'
                
                STREAM_CACHE[canal] = {
                    'm3u8_url': m3u8_url,
                    'base_url': base_url,
                    'expires': time.time() + CACHE_TTL
                }
                print(f"🔄 Caché actualizada para {canal}")
            else:
                print(f"❌ Fallo al obtener stream para {canal}")
                abort(500, "No se pudo obtener el stream")

    cache_info = STREAM_CACHE[canal]
    m3u8_url = cache_info['m3u8_url']
    base_url = cache_info['base_url']

    try:
        # Obtener el M3U8 original con headers actualizados
        r = requests.get(
            m3u8_url, 
            headers={**HEADERS, "Referer": "https://streamtpglobal.com/"},
            timeout=15
        )
        r.raise_for_status()

        # Reescribir el contenido
        content = r.text
        rewritten_content = rewrite_m3u8(content, base_url, canal)

        # Configurar headers para HLS
        response = Response(rewritten_content, mimetype="application/x-mpegurl")
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response

    except Exception as e:
        print(f"❌ Error al obtener .m3u8: {e}")
        # Intentar refrescar el caché si falla
        with LOCK:
            STREAM_CACHE.pop(canal, None)
        abort(502, "Error de conexión con el origen")

@app.route('/proxy/segment/<canal>')
def proxy_segment(canal):
    if canal not in CHANNELS:
        abort(404, "Canal no encontrado")

    encoded_url = request.args.get("real_url")
    if not encoded_url:
        abort(400, "URL no especificada")

    try:
        # Decodificar la URL
        real_url = unquote(encoded_url)
        
        # Descargar el recurso (ts, key, m3u8)
        r = requests.get(
            real_url, 
            headers={**HEADERS, "Referer": "https://streamtpglobal.com/"},
            stream=True, 
            timeout=20,
            verify=False
        )
        r.raise_for_status()

        # Determinar tipo de contenido
        content_type = 'video/MP2T'  # Por defecto para segmentos TS
        if '.key' in real_url:
            content_type = 'application/octet-stream'
        elif '.m3u8' in real_url:
            content_type = 'application/x-mpegurl'

        # Configurar headers
        headers = {
            'Content-Type': content_type,
            'Access-Control-Allow-Origin': '*',
            'Cache-Control': 'no-cache, max-age=0'
        }

        # Devolver el contenido
        return Response(
            r.iter_content(chunk_size=8192),
            status=r.status_code,
            headers=headers,
            content_type=content_type
        )

    except requests.exceptions.RequestException as e:
        print(f"❌ Error de red al obtener segmento: {e}")
        abort(502, "Error de red")
    except Exception as e:
        print(f"❌ Error inesperado al obtener segmento: {e}")
        abort(500, "Error interno")

@app.route('/m3u')
def generate_m3u():
    base = request.host_url.rstrip("/")
    lines = ["#EXTM3U x-tvg-url=\"https://iptv-org.github.io/epg/guides/tvplus.com.epg.xml\""]

    for canal in CHANNELS:
        lines.append(
            f'#EXTINF:-1 tvg-id="{canal}" tvg-name="{canal.title()}" '
            f'group-title="StreamTPGlobal",{canal.title()}\n'
            f'{base}/stream/{canal}.m3u8'
        )

    response = Response("\n".join(lines), mimetype="application/x-mpegurl")
    response.headers['Content-Disposition'] = 'attachment; filename="streamtpglobal_proxy.m3u"'
    return response

@app.route('/')
def home():
    base = request.host_url.rstrip("/")
    links = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>📡 Proxy HLS de StreamTPGlobal</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
            h1 { color: #333; }
            ul { list-style-type: none; padding: 0; }
            li { padding: 8px 0; border-bottom: 1px solid #eee; }
            a { text-decoration: none; color: #0066cc; }
            a:hover { text-decoration: underline; }
            .btn { 
                display: inline-block; 
                background: #0066cc; 
                color: white; 
                padding: 10px 15px; 
                border-radius: 5px; 
                margin-top: 20px; 
            }
            .btn:hover { background: #0055aa; }
            .status { 
                padding: 3px 8px; 
                border-radius: 3px; 
                font-size: 0.8em;
                margin-left: 10px;
            }
            .status-active { background: #4CAF50; color: white; }
            .status-inactive { background: #f44336; color: white; }
        </style>
    </head>
    <body>
        <h1>📡 Proxy HLS de StreamTPGlobal</h1>
        <p>Proxy que elimina restricciones de IP y token para los canales.</p>
        <ul>
    '''
    
    for canal in CHANNELS:
        cache_status = "🟢" if canal in STREAM_CACHE else "🔴"
        links += f'''
        <li>
            {cache_status} <a href="/stream/{canal}.m3u8">{canal}</a> | 
            <a href="{base}/stream/{canal}.m3u8" target="_blank">🔗 URL</a>
        </li>'''
    
    links += '''
        </ul>
        <a href="/m3u" class="btn">📥 Descargar lista M3U completa</a>
        <p><small>Actualización automática cada 5 minutos | Canales en caché: {}/{}</small></p>
    </body>
    </html>
    '''.format(len(STREAM_CACHE), len(CHANNELS))
    return links

# Refresco automático en segundo plano
def background_refresh():
    while True:
        print("\n🔄 Iniciando actualización de caché...")
        start_time = time.time()
        updated = 0
        
        for canal in CHANNELS:
            try:
                print(f"  🔍 Actualizando {canal}...")
                m3u8_url = extract_m3u8_url(canal)
                if m3u8_url:
                    parsed = urlparse(m3u8_url)
                    base_url = f"{parsed.scheme}://{parsed.netloc}{os.path.dirname(parsed.path)}/"
                    if not base_url.endswith('/'):
                        base_url += '/'
                    
                    with LOCK:
                        STREAM_CACHE[canal] = {
                            'm3u8_url': m3u8_url,
                            'base_url': base_url,
                            'expires': time.time() + CACHE_TTL
                        }
                    updated += 1
                    print(f"  ✅ {canal} actualizado")
                else:
                    print(f"  ⚠️ No se pudo actualizar {canal}")
            except Exception as e:
                print(f"  ❌ Error actualizando {canal}: {e}")
        
        elapsed = time.time() - start_time
        print(f"✅ Actualización completada: {updated}/{len(CHANNELS)} canales en {elapsed:.2f}s")
        print(f"⏳ Próxima actualización en 4 minutos...")
        time.sleep(240)

if __name__ == '__main__':
    # Precargar caché al iniciar
    print("⏳ Precargando caché de canales...")
    for canal in CHANNELS:
        threading.Thread(target=extract_m3u8_url, args=(canal,), daemon=True).start()
    time.sleep(5)
    
    # Iniciar hilo de refresco
    refresh_thread = threading.Thread(target=background_refresh, daemon=True)
    refresh_thread.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
