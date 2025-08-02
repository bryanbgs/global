#!/usr/bin/env python3
"""
Proxy Inverso M3U8 Extractor - Versión para Render
Extrae URLs M3U8 de streamtpglobal.com y las sirve sin restricciones de IP
"""

import asyncio
import aiohttp
import re
import os
import logging
from urllib.parse import urljoin, urlparse, parse_qs
from aiohttp import web, ClientSession, ClientTimeout
import json
import time
from typing import Dict, List, Optional
import threading

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class M3U8ProxyServer:
    def __init__(self, port: int = 8080):
        self.port = port
        self.app = web.Application()
        self.session: Optional[ClientSession] = None
        self.channel_cache: Dict[str, dict] = {}
        self.cache_ttl = 300  # 5 minutos de cache
        
        # Headers para simular navegador real
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9,es;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        }
        
        self.setup_routes()
        
    def setup_routes(self):
        """Configura las rutas del servidor"""
        self.app.router.add_get('/', self.home)
        self.app.router.add_get('/playlist.m3u8', self.generate_playlist)
        self.app.router.add_get('/channel/{channel}', self.serve_channel)
        self.app.router.add_get('/proxy/{channel}', self.proxy_m3u8)
        self.app.router.add_get('/segment/{channel}/{path:.*}', self.proxy_segment)
        self.app.router.add_post('/upload_channels', self.upload_channels)
        
        # Middleware para CORS
        self.app.middlewares.append(self.cors_middleware)
        
    @web.middleware
    async def cors_middleware(self, request, handler):
        """Middleware para manejar CORS"""
        response = await handler(request)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response
        
    async def init_session(self):
        """Inicializa la sesión HTTP"""
        if not self.session or self.session.closed:
            timeout = ClientTimeout(total=30, connect=10)
            self.session = ClientSession(
                timeout=timeout,
                headers=self.headers,
                connector=aiohttp.TCPConnector(ssl=False, limit=100)
            )
            
    async def cleanup_session(self):
        """Limpia la sesión HTTP"""
        if self.session and not self.session.closed:
            await self.session.close()
            
    async def extract_m3u8_url(self, channel: str) -> Optional[str]:
        """Extrae la URL M3U8 real de streamtpglobal"""
        await self.init_session()
        
        try:
            url = f"https://streamtpglobal.com/global1.php?stream={channel}"
            logger.info(f"Extrayendo M3U8 para canal: {channel}")
            
            async with self.session.get(url, headers=self.headers) as response:
                if response.status != 200:
                    logger.error(f"Error HTTP {response.status} para canal {channel}")
                    return None
                    
                html_content = await response.text()
                
                # Buscar URLs M3U8 usando múltiples patrones
                patterns = [
                    r'https://[^/]+\.crackstreamslivehd\.com/[^/]+/tracks-v1a1/mono\.m3u8\?ip=[^&]+&token=[^"\s]+',
                    r'https://[^"]+\.m3u8\?ip=[^&]+&token=[^"]+',
                    r'source:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
                    r'file:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
                    r'src:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
                    r'var\s+\w+\s*=\s*["\']([^"\']+\.m3u8[^"\']*)["\']'
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, html_content, re.IGNORECASE)
                    if matches:
                        m3u8_url = matches[0]
                        logger.info(f"URL M3U8 encontrada para {channel}: {m3u8_url}")
                        return m3u8_url
                
                logger.warning(f"No se encontró URL M3U8 para canal: {channel}")
                logger.debug(f"HTML content preview: {html_content[:500]}...")
                return None
                
        except Exception as e:
            logger.error(f"Error extrayendo M3U8 para {channel}: {str(e)}")
            return None
            
    async def get_cached_channel(self, channel: str) -> Optional[dict]:
        """Obtiene información del canal desde cache"""
        if channel in self.channel_cache:
            cache_data = self.channel_cache[channel]
            if time.time() - cache_data['timestamp'] < self.cache_ttl:
                return cache_data
            else:
                del self.channel_cache[channel]
        return None
        
    async def cache_channel(self, channel: str, m3u8_url: str):
        """Cachea información del canal"""
        self.channel_cache[channel] = {
            'url': m3u8_url,
            'timestamp': time.time(),
            'base_url': '/'.join(m3u8_url.split('/')[:-1]) + '/'
        }
        
    async def home(self, request: web.Request) -> web.Response:
        """Página principal"""
        host = request.headers.get('Host', 'localhost:8080')
        base_url = f"https://{host}" if 'render' in host else f"http://{host}"
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>M3U8 Proxy Server</title>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
                .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                textarea {{ width: 100%; height: 200px; padding: 10px; border: 1px solid #ddd; border-radius: 5px; }}
                button {{ padding: 12px 25px; margin: 10px 0; background: #007bff; color: white; border: none; border-radius: 5px; cursor: pointer; }}
                button:hover {{ background: #0056b3; }}
                .url {{ background: #f8f9fa; padding: 15px; margin: 10px 0; border-radius: 5px; border-left: 4px solid #007bff; }}
                .status {{ padding: 10px; margin: 10px 0; border-radius: 5px; }}
                .success {{ background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }}
                .error {{ background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }}
                a {{ color: #007bff; text-decoration: none; }}
                a:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🎬 M3U8 Proxy Server</h1>
                <p>Servidor proxy para extraer y servir streams M3U8 sin restricciones de IP</p>
                
                <h2>📋 Subir Lista de Canales</h2>
                <form id="channelForm">
                    <textarea id="channels" placeholder="Ingresa los canales, uno por línea. Ejemplo:&#10;espn&#10;fox1&#10;cnn&#10;discovery"></textarea>
                    <br>
                    <button type="submit">🚀 Procesar Canales</button>
                </form>
                
                <div id="status"></div>
                
                <h2>📺 Playlist Principal</h2>
                <div class="url">
                    <strong>📁 Playlist M3U8 Completa:</strong><br>
                    <a href="/playlist.m3u8" target="_blank">{base_url}/playlist.m3u8</a>
                </div>
                
                <h2>🎯 Canales Individuales</h2>
                <div id="channelList"></div>
                
                <h2>📖 Instrucciones</h2>
                <ul>
                    <li>Sube tu lista de canales usando el formulario</li>
                    <li>Usa la URL del playlist principal en tu reproductor favorito</li>
                    <li>También puedes acceder a canales individuales</li>
                    <li>Las URLs generadas no tienen restricciones de IP</li>
                </ul>
                
                <script>
                    const baseUrl = '{base_url}';
                    
                    document.getElementById('channelForm').onsubmit = async (e) => {{
                        e.preventDefault();
                        const channels = document.getElementById('channels').value;
                        const statusDiv = document.getElementById('status');
                        
                        if (!channels.trim()) {{
                            statusDiv.innerHTML = '<div class="status error">❌ Por favor ingresa al menos un canal</div>';
                            return;
                        }}
                        
                        statusDiv.innerHTML = '<div class="status">⏳ Procesando canales...</div>';
                        
                        try {{
                            const response = await fetch('/upload_channels', {{
                                method: 'POST',
                                headers: {{'Content-Type': 'application/json'}},
                                body: JSON.stringify({{channels: channels}})
                            }});
                            
                            const result = await response.json();
                            
                            if (result.status === 'success') {{
                                statusDiv.innerHTML = '<div class="status success">✅ Canales procesados correctamente</div>';
                                updateChannelList(result.channels);
                            }} else {{
                                statusDiv.innerHTML = `<div class="status error">❌ Error: ${{result.message}}</div>`;
                            }}
                        }} catch (error) {{
                            statusDiv.innerHTML = `<div class="status error">❌ Error de conexión: ${{error.message}}</div>`;
                        }}
                    }};
                    
                    function updateChannelList(channels) {{
                        const list = document.getElementById('channelList');
                        if (channels.length === 0) {{
                            list.innerHTML = '<p>No hay canales configurados</p>';
                            return;
                        }}
                        
                        list.innerHTML = channels.map(channel => 
                            `<div class="url">
                                <strong>📺 ${{channel.toUpperCase()}}:</strong><br>
                                <a href="/channel/${{channel}}" target="_blank">${{baseUrl}}/channel/${{channel}}</a>
                            </div>`
                        ).join('');
                    }}
                    
                    // Cargar canales existentes al inicio
                    fetch('/playlist.m3u8').then(response => {{
                        if (response.ok) {{
                            return response.text();
                        }}
                    }}).then(data => {{
                        if (data && data.includes('#EXTINF')) {{
                            const channels = data.match(/#EXTINF:-1,([^\\n]+)/g);
                            if (channels) {{
                                const channelNames = channels.map(line => line.replace('#EXTINF:-1,', '').toLowerCase());
                                updateChannelList(channelNames);
                            }}
                        }}
                    }}).catch(() => {{
                        // Ignorar errores de carga inicial
                    }});
                </script>
            </div>
        </body>
        </html>
        """
        
        return web.Response(text=html, content_type='text/html')
        
    async def upload_channels(self, request: web.Request) -> web.Response:
        """Procesa la lista de canales subida"""
        try:
            data = await request.json()
            channels_text = data.get('channels', '')
            channels = [ch.strip() for ch in channels_text.split('\n') if ch.strip()]
            
            if not channels:
                return web.json_response({'status': 'error', 'message': 'No se encontraron canales válidos'})
            
            # Guardar canales en archivo
            try:
                with open('channels.txt', 'w', encoding='utf-8') as f:
                    for channel in channels:
                        f.write(f"{channel}\n")
            except Exception as e:
                logger.error(f"Error guardando canales: {str(e)}")
                
            return web.json_response({'status': 'success', 'channels': channels})
            
        except Exception as e:
            logger.error(f"Error procesando canales: {str(e)}")
            return web.json_response({'status': 'error', 'message': str(e)})
            
    async def load_channels(self) -> List[str]:
        """Carga la lista de canales desde archivo"""
        try:
            if os.path.exists('channels.txt'):
                with open('channels.txt', 'r', encoding='utf-8') as f:
                    return [line.strip() for line in f if line.strip()]
            return []
        except Exception as e:
            logger.error(f"Error cargando canales: {str(e)}")
            return []
            
    async def generate_playlist(self, request: web.Request) -> web.Response:
        """Genera playlist M3U8 con todos los canales"""
        try:
            channels = await self.load_channels()
            if not channels:
                return web.Response(text="#EXTM3U\n# No hay canales configurados", 
                                  content_type='application/vnd.apple.mpegurl',
                                  status=200)
                
            host = request.headers.get('Host', 'localhost:8080')
            base_url = f"https://{host}" if 'render' in host else f"http://{host}"
            
            m3u8_content = "#EXTM3U\n"
            
            for channel in channels:
                m3u8_content += f"#EXTINF:-1,{channel.upper()}\n"
                m3u8_content += f"{base_url}/channel/{channel}\n"
                
            return web.Response(
                text=m3u8_content,
                content_type='application/vnd.apple.mpegurl',
                headers={
                    'Access-Control-Allow-Origin': '*',
                    'Cache-Control': 'no-cache'
                }
            )
            
        except Exception as e:
            logger.error(f"Error generando playlist: {str(e)}")
            return web.Response(text="Error interno del servidor", status=500)
            
    async def serve_channel(self, request: web.Request) -> web.Response:
        """Sirve un canal específico"""
        channel = request.match_info['channel']
        
        try:
            # Verificar cache
            cached = await self.get_cached_channel(channel)
            if cached:
                return await self.proxy_m3u8_content(cached['url'])
                
            # Extraer nueva URL
            m3u8_url = await self.extract_m3u8_url(channel)
            if not m3u8_url:
                return web.Response(text=f"Canal {channel} no disponible", status=404)
                
            # Cachear y servir
            await self.cache_channel(channel, m3u8_url)
            return await self.proxy_m3u8_content(m3u8_url)
            
        except Exception as e:
            logger.error(f"Error sirviendo canal {channel}: {str(e)}")
            return web.Response(text="Error interno del servidor", status=500)
            
    async def proxy_m3u8_content(self, original_url: str) -> web.Response:
        """Obtiene y modifica el contenido M3U8"""
        await self.init_session()
        
        try:
            async with self.session.get(original_url, headers=self.headers) as response:
                if response.status != 200:
                    return web.Response(text="Stream no disponible", status=404)
                    
                content = await response.text()
                
                # Modificar URLs relativas en el M3U8
                base_url = '/'.join(original_url.split('/')[:-1]) + '/'
                modified_content = self.modify_m3u8_content(content, base_url)
                
                return web.Response(
                    text=modified_content,
                    content_type='application/vnd.apple.mpegurl',
                    headers={
                        'Access-Control-Allow-Origin': '*',
                        'Cache-Control': 'no-cache'
                    }
                )
                
        except Exception as e:
            logger.error(f"Error obteniendo contenido M3U8: {str(e)}")
            return web.Response(text="Error obteniendo stream", status=500)
            
    def modify_m3u8_content(self, content: str, base_url: str) -> str:
        """Modifica el contenido M3U8 para usar el proxy"""
        lines = content.split('\n')
        modified_lines = []
        
        for line in lines:
            if line.strip() and not line.startswith('#'):
                # Es una URL de segmento
                if line.startswith('http'):
                    # URL absoluta - mantener como está por ahora
                    modified_lines.append(line)
                else:
                    # URL relativa - convertir a absoluta
                    absolute_url = urljoin(base_url, line)
                    modified_lines.append(absolute_url)
            else:
                modified_lines.append(line)
                
        return '\n'.join(modified_lines)
        
    async def proxy_m3u8(self, request: web.Request) -> web.Response:
        """Proxy para archivos M3U8"""
        channel = request.match_info['channel']
        return await self.serve_channel(request)
        
    async def proxy_segment(self, request: web.Request) -> web.Response:
        """Proxy para segmentos de video"""
        channel = request.match_info['channel']
        path = request.match_info['path']
        
        await self.init_session()
        
        try:
            cached = await self.get_cached_channel(channel)
            if not cached:
                return web.Response(text="Canal no encontrado", status=404)
                
            segment_url = cached['base_url'] + path
            
            async with self.session.get(segment_url, headers=self.headers) as response:
                if response.status != 200:
                    return web.Response(text="Segmento no disponible", status=404)
                    
                content = await response.read()
                content_type = response.headers.get('content-type', 'video/mp2t')
                
                return web.Response(
                    body=content,
                    content_type=content_type,
                    headers={'Access-Control-Allow-Origin': '*'}
                )
                
        except Exception as e:
            logger.error(f"Error proxy segmento: {str(e)}")
            return web.Response(text="Error obteniendo segmento", status=500)

# Instancia global del servidor
proxy_server = M3U8ProxyServer()

# Función para crear la aplicación WSGI
def create_app():
    """Crea la aplicación para Gunicorn"""
    return proxy_server.app

# Variable app requerida por Gunicorn
app = create_app()

# Función principal para desarrollo local
async def main():
    """Función principal para desarrollo local"""
    port = int(os.environ.get('PORT', 8080))
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"Servidor iniciado en http://0.0.0.0:{port}")
    logger.info(f"Playlist disponible en: http://0.0.0.0:{port}/playlist.m3u8")
    
    try:
        await asyncio.Future()  # Mantener el servidor corriendo
    except KeyboardInterrupt:
        logger.info("Deteniendo servidor...")
    finally:
        await proxy_server.cleanup_session()
        await runner.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
