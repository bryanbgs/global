# app.py - Versión definitiva para streamtpglobal.com
#!/usr/bin/env python3
"""
Proxy Inverso M3U8 Extractor
Extrae URLs M3U8 de streamtpglobal.com y las sirve sin restricciones de IP
"""

import asyncio
import aiohttp
import re
import os
import logging
from urllib.parse import urljoin, urlparse, parse_qs
from aiohttp import web, ClientSession, ClientTimeout
from aiohttp.web import Response, Request
import json
import time
from typing import Dict, List, Optional
import base64
import hashlib

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
        
    async def init_session(self):
        """Inicializa la sesión HTTP"""
        timeout = ClientTimeout(total=30, connect=10)
        self.session = ClientSession(
            timeout=timeout,
            headers=self.headers,
            connector=aiohttp.TCPConnector(ssl=False, limit=100)
        )
        
    async def cleanup_session(self):
        """Limpia la sesión HTTP"""
        if self.session:
            await self.session.close()
            
    async def extract_m3u8_url(self, channel: str) -> Optional[str]:
        """Extrae la URL M3U8 real de streamtpglobal"""
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
                    r'src:\s*["\']([^"\']+\.m3u8[^"\']*)["\']'
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, html_content, re.IGNORECASE)
                    if matches:
                        m3u8_url = matches[0]
                        logger.info(f"URL M3U8 encontrada para {channel}: {m3u8_url}")
                        return m3u8_url
                
                # Buscar en JavaScript embebido
                js_pattern = r'var\s+\w+\s*=\s*["\']([^"\']+\.m3u8[^"\']*)["\']'
                js_matches = re.findall(js_pattern, html_content, re.IGNORECASE)
                if js_matches:
                    return js_matches[0]
                
                logger.warning(f"No se encontró URL M3U8 para canal: {channel}")
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
        
    async def home(self, request: Request) -> Response:
        """Página principal"""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>M3U8 Proxy Server</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                .container { max-width: 800px; margin: 0 auto; }
                textarea { width: 100%; height: 200px; }
                button { padding: 10px 20px; margin: 10px 0; }
                .url { background: #f0f0f0; padding: 10px; margin: 10px 0; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>M3U8 Proxy Server</h1>
                <p>Servidor proxy para extraer y servir streams M3U8 sin restricciones de IP</p>
                
                <h2>Subir Lista de Canales</h2>
                <form id="channelForm">
                    <textarea id="channels" placeholder="Ingresa los canales, uno por línea. Ejemplo:&#10;espn&#10;fox1&#10;cnn"></textarea>
                    <br>
                    <button type="submit">Procesar Canales</button>
                </form>
                
                <h2>URLs Generadas</h2>
                <div class="url">
                    <strong>Playlist M3U8:</strong><br>
                    <a href="/playlist.m3u8" target="_blank">{{base_url}}/playlist.m3u8</a>
                </div>
                
                <h2>Canales Individuales</h2>
                <div id="channelList"></div>
                
                <script>
                    const baseUrl = window.location.origin;
                    document.querySelector('.url a').textContent = baseUrl + '/playlist.m3u8';
                    
                    document.getElementById('channelForm').onsubmit = async (e) => {
                        e.preventDefault();
                        const channels = document.getElementById('channels').value;
                        
                        const response = await fetch('/upload_channels', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({channels: channels})
                        });
                        
                        const result = await response.json();
                        updateChannelList(result.channels);
                    };
                    
                    function updateChannelList(channels) {
                        const list = document.getElementById('channelList');
                        list.innerHTML = channels.map(channel => 
                            `<div class="url">
                                <strong>${channel}:</strong><br>
                                <a href="/channel/${channel}" target="_blank">${baseUrl}/channel/${channel}</a>
                            </div>`
                        ).join('');
                    }
                </script>
            </div>
        </body>
        </html>
        """.replace('{{base_url}}', f"http://localhost:{self.port}")
        
        return Response(text=html, content_type='text/html')
        
    async def upload_channels(self, request: Request) -> Response:
        """Procesa la lista de canales subida"""
        try:
            data = await request.json()
            channels_text = data.get('channels', '')
            channels = [ch.strip() for ch in channels_text.split('\n') if ch.strip()]
            
            # Guardar canales en archivo
            with open('channels.txt', 'w') as f:
                for channel in channels:
                    f.write(f"{channel}\n")
                    
            return web.json_response({'status': 'success', 'channels': channels})
            
        except Exception as e:
            logger.error(f"Error procesando canales: {str(e)}")
            return web.json_response({'status': 'error', 'message': str(e)})
            
    async def load_channels(self) -> List[str]:
        """Carga la lista de canales desde archivo"""
        try:
            if os.path.exists('channels.txt'):
                with open('channels.txt', 'r') as f:
                    return [line.strip() for line in f if line.strip()]
            return []
        except Exception as e:
            logger.error(f"Error cargando canales: {str(e)}")
            return []
            
    async def generate_playlist(self, request: Request) -> Response:
        """Genera playlist M3U8 con todos los canales"""
        try:
            channels = await self.load_channels()
            if not channels:
                return Response(text="No hay canales configurados", status=404)
                
            base_url = f"http://{request.host}"
            
            m3u8_content = "#EXTM3U\n"
            
            for channel in channels:
                m3u8_content += f"#EXTINF:-1,{channel.upper()}\n"
                m3u8_content += f"{base_url}/channel/{channel}\n"
                
            return Response(
                text=m3u8_content,
                content_type='application/vnd.apple.mpegurl',
                headers={
                    'Access-Control-Allow-Origin': '*',
                    'Cache-Control': 'no-cache'
                }
            )
            
        except Exception as e:
            logger.error(f"Error generando playlist: {str(e)}")
            return Response(text="Error interno del servidor", status=500)
            
    async def serve_channel(self, request: Request) -> Response:
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
                return Response(text=f"Canal {channel} no disponible", status=404)
                
            # Cachear y servir
            await self.cache_channel(channel, m3u8_url)
            return await self.proxy_m3u8_content(m3u8_url)
            
        except Exception as e:
            logger.error(f"Error sirviendo canal {channel}: {str(e)}")
            return Response(text="Error interno del servidor", status=500)
            
    async def proxy_m3u8_content(self, original_url: str) -> Response:
        """Obtiene y modifica el contenido M3U8"""
        try:
            async with self.session.get(original_url, headers=self.headers) as response:
                if response.status != 200:
                    return Response(text="Stream no disponible", status=404)
                    
                content = await response.text()
                
                # Modificar URLs relativas en el M3U8
                base_url = '/'.join(original_url.split('/')[:-1]) + '/'
                modified_content = self.modify_m3u8_content(content, base_url)
                
                return Response(
                    text=modified_content,
                    content_type='application/vnd.apple.mpegurl',
                    headers={
                        'Access-Control-Allow-Origin': '*',
                        'Cache-Control': 'no-cache'
                    }
                )
                
        except Exception as e:
            logger.error(f"Error obteniendo contenido M3U8: {str(e)}")
            return Response(text="Error obteniendo stream", status=500)
            
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
        
    async def proxy_m3u8(self, request: Request) -> Response:
        """Proxy para archivos M3U8"""
        channel = request.match_info['channel']
        return await self.serve_channel(request)
        
    async def proxy_segment(self, request: Request) -> Response:
        """Proxy para segmentos de video"""
        channel = request.match_info['channel']
        path = request.match_info['path']
        
        try:
            cached = await self.get_cached_channel(channel)
            if not cached:
                return Response(text="Canal no encontrado", status=404)
                
            segment_url = cached['base_url'] + path
            
            async with self.session.get(segment_url, headers=self.headers) as response:
                if response.status != 200:
                    return Response(text="Segmento no disponible", status=404)
                    
                content = await response.read()
                content_type = response.headers.get('content-type', 'video/mp2t')
                
                return Response(
                    body=content,
                    content_type=content_type,
                    headers={'Access-Control-Allow-Origin': '*'}
                )
                
        except Exception as e:
            logger.error(f"Error proxy segmento: {str(e)}")
            return Response(text="Error obteniendo segmento", status=500)
            
    async def start_server(self):
        """Inicia el servidor"""
        await self.init_session()
        
        runner = web.AppRunner(self.app)
        await runner.setup()
        
        site = web.TCPSite(runner, '0.0.0.0', self.port)
        await site.start()
        
        logger.info(f"Servidor iniciado en http://0.0.0.0:{self.port}")
        logger.info(f"Playlist disponible en: http://0.0.0.0:{self.port}/playlist.m3u8")
        
        try:
            await asyncio.Future()  # Mantener el servidor corriendo
        except KeyboardInterrupt:
            logger.info("Deteniendo servidor...")
        finally:
            await self.cleanup_session()
            await runner.cleanup()

async def main():
    """Función principal"""
    port = int(os.environ.get('PORT', 8080))
    server = M3U8ProxyServer(port=port)
    await server.start_server()

if __name__ == '__main__':
    asyncio.run(main())
