# app.py - Versión definitiva para streamtpglobal.com
import os
import re
import time
import threading
import requests
from flask import Flask, Response, request, abort, url_for
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, quote, unquote

app = Flask(__name__)

# URL base CORREGIDA para streamtpglobal.com
BASE_URL = "https://streamtpglobal.com/global1.php?stream={}"

# Headers COMPLETOS simulando exactamente lo que envía el navegador
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "es-419,es;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Connection": "keep-alive",
    "Referer": "https://streamtpglobal.com/",
    "Origin": "https://streamtpglobal.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
    "Priority": "u=1, i",
    "Sec-Ch-Ua": '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"'
}

STREAM_CACHE = {}
CACHE_TTL = 300
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
        print("⚠️ canales.txt no encontrado")
        # Incluimos fox1ar que es el canal que estás probando
        channels = ["fox1ar", "espn", "espn2", "foxsports", "beinsports"]
    return channels

CHANNELS = load_channels()

def extract_m3u8_url(canal):
    url = BASE_URL.format(canal)
    try:
        print(f"🔍 Iniciando extracción para {canal} desde {url}")
        session = requests.Session()
        session.headers.update(HEADERS)
        
        # Paso 1: Obtener la página principal
        print(f"🌐 Obteniendo página principal...")
        response = session.get(url, timeout=20)
        response.raise_for_status()
        print(f"✅ Página principal obtenida (tamaño: {len(response.text)} bytes)")
        
        # Verificar si hay Cloudflare
        if "cloudflare" in response.text.lower() or "checking your browser" in response.text.lower():
            print("🛡️ Detectado Cloudflare - intentando resolver...")
            # Simular comportamiento de navegador más realista
            time.sleep(1)  # Simular tiempo de carga del navegador
            response = session.get(url, timeout=25)
        
        # Paso 2: Buscar la URL M3U8 en el HTML
        print(f"🔍 Buscando URL M3U8 en el contenido...")
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Método 1: Buscar en todos los scripts
        scripts = soup.find_all('script')
        print(f"🔍 Analizando {len(scripts)} scripts...")
        for i, script in enumerate(scripts):
            if script.string and "m3u8" in script.string:
                print(f"📝 Script #{i} contiene 'm3u8', analizando...")
                # Regex mejorada para capturar cualquier URL M3U8
                match = re.search(r'(https?://[^\s\'"\\]+\.m3u8[^\s\'"]*)', script.string)
                if match:
                    m3u8_url = match.group(1)
                    print(f"✅ M3U8 encontrado en script: {m3u8_url}")
                    return m3u8_url
        
        # Método 2: Buscar en iframes
        iframes = soup.find_all('iframe')
        print(f"🔍 Analizando {len(iframes)} iframes...")
        for i, iframe in enumerate(iframes):
            src = iframe.get('src', '')
            if src:
                print(f"📝 Iframe #{i} src: {src}")
                if "m3u8" in src:
                    print(f"✅ M3U8 encontrado en iframe src: {src}")
                    return src
                
                # Intentar cargar el iframe
                if src.startswith('http'):
                    iframe_url = src
                else:
                    iframe_url = urljoin(url, src)
                
                print(f"🌐 Cargando iframe desde: {iframe_url}")
                iframe_response = session.get(iframe_url, timeout=20)
                iframe_match = re.search(r'(https?://[^\s\'"\\]+\.m3u8[^\s\'"]*)', iframe_response.text)
                if iframe_match:
                    m3u8_url = iframe_match.group(1)
                    print(f"✅ M3U8 encontrado en iframe cargado: {m3u8_url}")
                    return m3u8_url
        
        # Método 3: Buscar en todo el HTML
        print("🔍 Buscando en todo el HTML...")
        match = re.search(r'(https?://[^\s\'"\\]+\.m3u8[^\s\'"]*)', response.text)
        if match:
            m3u8_url = match.group(1)
            print(f"✅ M3U8 encontrado en HTML: {m3u8_url}")
            return m3u8_url
        
        # Método 4: Buscar en elementos específicos (común en estos sitios)
        print("🔍 Buscando en elementos específicos...")
        video_elements = soup.find_all(['video', 'source', 'iframe', 'script'])
        for element in video_elements:
            for attr in ['src', 'data-src', 'data-url', 'src-hls', 'source']:
                value = element.get(attr, '')
                if value and "m3u8" in value:
                    if value.startswith('http'):
                        print(f"✅ M3U8 encontrado en {element.name}[{attr}]: {value}")
                        return value
                    else:
                        full_url = urljoin(url, value)
                        print(f"✅ M3U8 relativo encontrado en {element.name}[{attr}]: {full_url}")
                        return full_url
        
        print(f"❌ No se encontró URL M3U8 para {canal}")
        return None
        
    except Exception as e:
        print(f"❌ Error extrayendo m3u8 para {canal}: {str(e)}")
        import traceback
        print(f" traceback: {traceback.format_exc()}")
        return None

def rewrite_m3u8(content, base_url, canal):
    """Reescribe TODO el contenido del M3U8 para que todas las URLs pasen por el proxy"""
    print(f"🔄 Reescribiendo M3U8 para {canal}")
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
            print(f"🔗 Segmento encontrado: {abs_url}")
            # Codificar la URL para el proxy
            encoded_url = quote(abs_url, safe='')
            proxy_url = url_for('proxy_segment', canal=canal, real_url=encoded_url, _external=True)
            rewritten.append(proxy_url)
            in_segment = False
            continue
        # 3. Líneas de claves (EXT-X-KEY)
        if '#EXT-X-KEY' in stripped and 'URI="' in stripped:
            print(f"🔑 Clave encontrada: {stripped}")
            # Reescribir la URL de la clave
            new_line = re.sub(
                r'(URI=")([^"]+)"', 
                lambda m: f'{m.group(1)}{url_for("proxy_segment", canal=canal, real_url=quote(m.group(2), safe=""), _external=True)}"', 
                stripped
            )
            rewritten.append(new_line)
            continue
        # 4. Otras líneas (dejarlas igual)
        rewritten.append(line)
    
    rewritten_content = "\n".join(rewritten)
    print(f"📝 M3U8 reescrito (tamaño: {len(rewritten_content)} bytes)")
    return rewritten_content

@app.route('/stream/<canal>.m3u8')
def proxy_playlist(canal):
    if canal not in CHANNELS:
        print(f"❌ Canal '{canal}' no está en la lista de canales permitidos")
        abort(404, "Canal no encontrado")
    
    print(f"➡️ Solicitud recibida para /stream/{canal}.m3u8")
    
    # Obtener o actualizar caché
    cached = STREAM_CACHE.get(canal)
    if not cached or time.time() > cached.get('expires', 0):
        with LOCK:
            print(f"🔄 Actualizando caché para {canal}")
            m3u8_url = extract_m3u8_url(canal)
            if m3u8_url:
                # Calcular base_url correctamente
                parsed = urlparse(m3u8_url)
                base_url = f"{parsed.scheme}://{parsed.netloc}{os.path.dirname(parsed.path)}/"
                STREAM_CACHE[canal] = {
                    'm3u8_url': m3u8_url,
                    'base_url': base_url,
                    'expires': time.time() + CACHE_TTL
                }
                print(f"✅ M3U8 actualizado para {canal}: {m3u8_url}")
                print(f"🌐 Base URL: {base_url}")
            else:
                print(f"❌ No se pudo obtener el M3U8 para {canal}")
                abort(500, "No se pudo obtener el stream")
    
    cache_info = STREAM_CACHE[canal]
    m3u8_url = cache_info['m3u8_url']
    
    try:
        print(f"⬇️ Descargando M3U8 original: {m3u8_url}")
        # Obtener el M3U8 original con TODOS los headers necesarios
        r = requests.get(
            m3u8_url, 
            headers={**HEADERS, "Referer": "https://streamtpglobal.com/"},
            timeout=20,
            allow_redirects=True  # Importante para seguir redirecciones
        )
        print(f"📡 Estado de la respuesta M3U8: {r.status_code}")
        if r.status_code != 200:
            print(f"❌ Error HTTP {r.status_code} al obtener el M3U8")
            print(f"Contenido de error: {r.text[:500]}")
        
        r.raise_for_status()
        print(f"✅ M3U8 descargado exitosamente (tamaño: {len(r.text)} bytes)")
        
        # Reescribir el contenido
        content = r.text
        rewritten_content = rewrite_m3u8(content, cache_info['base_url'], canal)
        
        # Configurar headers para HLS
        response = Response(rewritten_content, mimetype="application/x-mpegurl")
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Content-Type'] = 'application/x-mpegurl'
        response.headers['Accept-Ranges'] = 'bytes'
        print(f"✅ Playlist reescrito y listo para enviar")
        return response
    except Exception as e:
        print(f"❌ Error al obtener .m3u8 para {canal}: {str(e)}")
        import traceback
        print(f" traceback: {traceback.format_exc()}")
        abort(502, "Error de conexión con el origen")

@app.route('/proxy/segment/<canal>')
def proxy_segment(canal):
    if canal not in CHANNELS:
        print(f"❌ Canal '{canal}' no está en la lista de canales permitidos")
        abort(404, "Canal no encontrado")
    
    encoded_url = request.args.get("real_url")
    if not encoded_url:
        print("❌ URL no especificada en la solicitud de segmento")
        abort(400, "URL no especificada")
    
    try:
        # Decodificar la URL
        real_url = unquote(encoded_url)
        print(f"➡️ Solicitud de segmento para {canal}: {real_url}")
        
        # Descargar el recurso (ts, key, m3u8) con TODOS los headers necesarios
        r = requests.get(
            real_url, 
            headers={**HEADERS, "Referer": "https://streamtpglobal.com/"},
            stream=True, 
            timeout=25,
            verify=False  # Necesario para algunos servidores con SSL mal configurado
        )
        print(f"📡 Estado de la respuesta segmento: {r.status_code}")
        if r.status_code != 200:
            print(f"❌ Error HTTP {r.status_code} al obtener el segmento")
        
        r.raise_for_status()
        print(f"✅ Segmento descargado exitosamente (tamaño: {len(r.content)} bytes)")
        
        # Configurar headers para HLS
        headers = {}
        for key, value in r.headers.items():
            # Mantener todos los headers importantes
            if key.lower() not in ['content-length', 'connection', 'transfer-encoding']:
                headers[key] = value
        
        # Asegurar headers necesarios para HLS
        headers['Access-Control-Allow-Origin'] = '*'
        headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        headers['Accept-Ranges'] = 'bytes'
        
        # Devolver el contenido
        return Response(
            r.iter_content(chunk_size=8192),
            status=r.status_code,
            headers=headers
        )
    except Exception as e:
        print(f"❌ Error proxyeando segmento para {canal}: {str(e)}")
        import traceback
        print(f" traceback: {traceback.format_exc()}")
        abort(502, "Error al obtener el segmento")

@app.route('/m3u')
def generate_m3u():
    base = request.host_url.rstrip("/")
    print(f"📥 Generando lista M3U para {len(CHANNELS)} canales")
    lines = ["#EXTM3U x-tvg-url=\"https://iptv-org.github.io/epg/guides/tvplus.com.epg.xml\""]
    for canal in CHANNELS:
        lines.append(
            f'#EXTINF:-1 tvg-id="{canal}" tvg-name="{canal.title()}" '
            f'group-title="StreamTPGlobal",{canal.title()}\n'
            f'{base}/stream/{canal}.m3u8'
        )
    response = Response("\n".join(lines), mimetype="application/x-mpegurl")
    response.headers['Content-Disposition'] = 'attachment; filename="playlist.m3u"'
    print(f"✅ Lista M3U generada exitosamente")
    return response

@app.route('/')
def home():
    base = request.host_url.rstrip("/")
    links = '<h1>📡 Proxy HLS de StreamTPGlobal</h1><ul>'
    for canal in CHANNELS:
        links += f'<li><a href="/stream/{canal}.m3u8">{canal}</a> | '
        links += f'<a href="{base}/stream/{canal}.m3u8" target="_blank">🔗 URL</a></li>'
    links += '</ul><p><a href="/m3u">📥 Descargar lista M3U</a></p>'
    return links

# Refresco automático en segundo plano
def background_refresh():
    while True:
        time.sleep(240)
        for canal in CHANNELS:
            print(f"🔄 Actualizando caché en segundo plano para {canal}")
            threading.Thread(target=extract_m3u8_url, args=(canal,), daemon=True).start()

if __name__ == '__main__':
    # Iniciar hilo de refresco
    threading.Thread(target=background_refresh, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Iniciando servidor en el puerto {port}")
    app.run(host="0.0.0.0", port=port, debug=True)
