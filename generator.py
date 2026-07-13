import json
import os
import urllib.parse

def generate_m3u():
    json_path = "streams.json"
    m3u_path = "playlist.m3u"
    
    if not os.path.exists(json_path):
        print(f"Hata: {json_path} dosyası bulunamadı!")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("list", {}).get("item", [])
    
    m3u_content = "#EXTM3U\n"
    
    for item in items:
        title = item.get("title", "Bilinmeyen Kanal")
        logo = item.get("thumb_square", "")
        group = item.get("group", "Genel")
        base_url = item.get("media_url") or item.get("url", "")
        
        if not base_url:
            continue
            
        # HTTP Başlıklarını (Headers) ayıkla
        headers = {}
        for i in range(1, 6):
            key = item.get(f"h{i}Key")
            val = item.get(f"h{i}Val")
            if key and val and key != "0" and val != "0":
                headers[key.lower()] = val

        # M3U Standart Etiketi (Logo ve Grup Bilgisi)
        m3u_content += f'#EXTINF:-1 tvg-logo="{logo}" group-title="{group}",{title}\n'
        
        # VLC ve standart oynatıcılar için HTTP Header parametreleri
        referer = headers.get("referer")
        origin = headers.get("origin")
        user_agent = headers.get("user-agent", "Mozilla/5.0")
        
        if referer:
            m3u_content += f'#EXTVLCOPT:http-referrer={referer}\n'
        if origin:
            m3u_content += f'#EXTVLCOPT:http-origin={origin}\n'
        m3u_content += f'#EXTVLCOPT:http-user-agent={user_agent}\n'
        
        # ExoPlayer ve bazı Android IPTV oynatıcıları için Header bilgilerini URL'ye ekleme formatı (Pipe yöntemi)
        # Örn: http://link.m3u8|Referer=http://taraftarium...&Origin=...
        query_params = []
        if referer:
            query_params.append(f"Referer={urllib.parse.quote(referer)}")
        if origin:
            query_params.append(f"Origin={urllib.parse.quote(origin)}")
        query_params.append(f"User-Agent={urllib.parse.quote(user_agent)}")
        
        final_url = f"{base_url}|{ '&'.join(query_params) }"
        m3u_content += f"{final_url}\n\n"

    with open(m3u_path, "w", encoding="utf-8") as f:
        f.write(m3u_content)
        
    print("playlist.m3u başarıyla güncellendi!")

if __name__ == "__main__":
    generate_m3u()
