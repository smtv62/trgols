import asyncio
import os
import sys
import re
import requests
from playwright.async_api import async_playwright

# ==================== KULLANICI AYARLARI ====================
BASLANGIC_DOMAIN_NUM = 1078  # Engellendikçe otomatik artacak başlangıç sayısı
CIKTI_DOSYASI = "taraftarium_canli.m3u"
SABIT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
# ============================================================

def get_active_taraftarium_url(start_num, max_attempts=30):
    """
    Sırasıyla domainleri sorgulayarak çalışan aktif adresi bulur.
    """
    headers = {'User-Agent': SABIT_USER_AGENT}
    print("🌐 Aktif Taraftarium domaini aranıyor...")
    
    for i in range(max_attempts):
        current_num = start_num + i
        test_url = f"https://taraftarium{current_num}.xyz"
        try:
            response = requests.get(test_url, headers=headers, timeout=5)
            if response.status_code == 200:
                print(f"✅ Aktif adres bulundu: {test_url}")
                return test_url
        except requests.RequestException:
            print(f"❌ {test_url} aktif değil, sonraki deneniyor...")
            continue
            
    print("⚠️ Aktif domain bulunamadı! Başlangıç adresiyle devam ediliyor.")
    return f"https://taraftarium{start_num}.xyz"

def m3u_temizle_ve_hazirla(dosya_yolu):
    with open(dosya_yolu, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
    print(f"🧹 {dosya_yolu} dosyası temizlendi.")

def m3u_listesine_ekle(url, kanal_adi, referer_url, dosya_yolu):
    with open(dosya_yolu, "a", encoding="utf-8") as f:
        optimize_url = f"{url}|User-Agent={SABIT_USER_AGENT}&Referer={referer_url}"
        f.write(f'#EXTINF:-1 group-title="Taraftarium",{kanal_adi}\n')
        f.write(f"{optimize_url}\n\n")
    print(f"🔹 [M3U GÜNCELLENDİ] {kanal_adi}")

async def main():
    # 1. Adım: Çalışan aktif adresi bul
    hedef_url = get_active_taraftarium_url(BASLANGIC_DOMAIN_NUM)
    
    m3u_temizle_ve_hazirla(CIKTI_DOSYASI)
    
    async with async_playwright() as p:
        print("[BAŞLIYOR] Playwright tarayıcısı başlatılıyor...")
        browser = await p.chromium.launch(headless=True) 
        
        context = await browser.new_context(
            user_agent=SABIT_USER_AGENT,
            viewport={"width": 1280, "height": 720}
        )
        page = await context.new_page()

        # Reklam ve analitik ağ isteklerini engelleyerek hızı artırıyoruz
        async def trafik_filtresi(route, request):
            if request.resource_type in ["stylesheet", "font", "image"] or any(x in request.url for x in ["google", "analytics", "doubleclick"]):
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", trafik_filtresi)

        # 2. Adım: Ana sayfadan kanal ID ve isimlerini dinamik olarak çek
        print(f"[ZİYARET] Menüyü taramak için {hedef_url} adresine gidiliyor...")
        try:
            await page.goto(hedef_url, wait_until="commit", timeout=45000)
            await page.wait_for_timeout(3000)
        except Exception as e:
            print(f"❌ Ana sayfaya erişilemedi: {e}")
            await browser.close()
            return

        # Sitedeki tüm a.channel-item elemanlarını yakala
        kanal_elementleri = await page.query_selector_all("a.channel-item")
        kesfedilen_kanallar = []

        for kutu in kanal_elementleri:
            href = await kutu.get_attribute("href")
            # id parametresini (Örn: b3) Regex ile çekiyoruz
            id_match = re.search(r"id=([^&]+)", href) if href else None
            
            if id_match:
                kanal_id = id_match.group(1)
                
                # Kanal ismini div.channel-name içerisinden alıyoruz
                kanal_adi_element = await kutu.query_selector(".channel-name")
                if kanal_adi_element:
                    kanal_adi = (await kanal_adi_element.inner_text()).strip()
                else:
                    kanal_adi = f"Kanal {kanal_id.upper()}"
                
                kesfedilen_kanallar.append({"id": kanal_id, "name": kanal_adi})

        total_kanal = len(kesfedilen_kanallar)
        print(f"📺 Sitede toplam {total_kanal} adet kanal menüsü başarıyla hafızaya alındı.\n")

        # 3. Adım: Her bir kanal sayfasına doğrudan giderek mono.m3u8 linkini yakala
        for index, kanal in enumerate(kesfedilen_kanallar):
            kanal_id = kanal["id"]
            kanal_adi = kanal["name"]
            
            kanal_sayfa_url = f"{hedef_url}/channel.html?id={kanal_id}"
            print(f"🔄 [{index + 1}/{total_kanal}] Aranıyor -> {kanal_adi} (ID: {kanal_id})")

            yakalanan_url = None
            link_yakalandi_olayi = asyncio.Event()

            # Bu kanala özel istek dinleyicisi
            async def istek_dinle(request):
                nonlocal yakalanan_url
                url = request.url
                # Ağ trafiğinde 'mono.m3u8' içeren ilk isteği yakala
                if "mono.m3u8" in url:
                    yakalanan_url = url
                    link_yakalandi_olayi.set()

            page.on("request", istek_dinle)

            try:
                # Doğrudan oynatıcının olduğu temiz sayfaya git
                await page.goto(kanal_sayfa_url, wait_until="commit", timeout=30000)
                
                try:
                    # Linkin düşmesi için maksimum 6 saniye bekle
                    await asyncio.wait_for(link_yakalandi_olayi.wait(), timeout=6.0)
                except asyncio.TimeoutError:
                    pass

                if yakalanan_url:
                    # .cfd veya benzeri yayın sunucusunun domainini referer yapmak için ayıkla
                    domain_match = re.search(r"https://[a-zA-Z0-9.-]+\.(cfd|com|net|xyz|club|org)", yakalanan_url)
                    referer = domain_match.group(0) + "/" if domain_match else f"{hedef_url}/"
                    
                    m3u_listesine_ekle(yakalanan_url, kanal_adi, referer, CIKTI_DOSYASI)
                else:
                    print(f"⚠️ {kanal_adi} için canlı yayın linki (mono.m3u8) ağ trafiğinde belirmedi.")

            except Exception as ex:
                print(f"❌ {kanal_adi} sayfası yüklenirken hata oluştu: {ex}")
            finally:
                # Bir sonraki kanal araması için dinleyiciyi kaldır
                page.remove_listener("request", istek_dinle)
                # Sayfalar arası geçişte şişme olmaması için kısa bir bekleme
                await page.wait_for_timeout(1000)

        print(f"\n🏁 İşlem bitti! Taptaze '{CIKTI_DOSYASI}' listeniz hazır.")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
