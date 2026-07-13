import asyncio
import os
import sys
import re
import requests
from playwright.async_api import async_playwright

# ==================== KULLANICI AYARLARI ====================
BASLANGIC_DOMAIN_NUM = 1078  # Engellendikçe artacak başlangıç sayısı
CIKTI_DOSYASI = "taraftarium_canli.m3u"
SABIT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
# ============================================================

def get_active_taraftarium_url(start_num, max_attempts=20):
    """
    Sırasıyla taraftarium1078.xyz, 1079.xyz... adreslerini sorgular.
    Çalışan aktif adresi tespit edip döner.
    """
    headers = {'User-Agent': SABIT_USER_AGENT}
    print("🌐 Aktif Taraftarium domaini aranıyor...")
    
    for i in range(max_attempts):
        current_num = start_num + i
        test_url = f"https://taraftarium{current_num}.xyz"
        try:
            # Hızlı kontrol için timeout süresini 5 saniye tutuyoruz
            response = requests.get(test_url, headers=headers, timeout=5)
            if response.status_code == 200:
                print(f"✅ Aktif adres bulundu: {test_url}")
                return test_url
        except requests.RequestException:
            print(f"❌ {test_url} yanıt vermedi. Bir sonraki deneniyor...")
            continue
            
    print("⚠️ Çalışan yeni bir domain bulunamadı! Başlangıç adresiyle devam ediliyor.")
    return f"https://taraftarium{start_num}.xyz"

def m3u_temizle_ve_hazirla(dosya_yolu):
    with open(dosya_yolu, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
    print(f"🧹 {dosya_yolu} dosyası temizlendi.")

def m3u_listesine_ekle(url, kanal_adi, logo_url, referer_url, dosya_yolu):
    with open(dosya_yolu, "a", encoding="utf-8") as f:
        optimize_url = f"{url}|User-Agent={SABIT_USER_AGENT}&Referer={referer_url}"
        if logo_url:
            f.write(f'#EXTINF:-1 tvg-logo="{logo_url}" group-title="Taraftarium",{kanal_adi}\n')
        else:
            f.write(f'#EXTINF:-1 group-title="Taraftarium",{kanal_adi}\n')
        f.write(f"{optimize_url}\n\n")
    print(f"🔹 [M3U GÜNCELLENDİ] {kanal_adi}")

async def main():
    # 1. Adım: Çalışan aktif adresi bul
    hedef_url = get_active_taraftarium_url(BASLANGIC_DOMAIN_NUM)
    
    m3u_temizle_ve_hazirla(CIKTI_DOSYASI)
    
    async with async_playwright() as p:
        print("[BAŞLIYOR] Playwright istek dinleyici başlatılıyor...")
        browser = await p.chromium.launch(headless=True) 
        
        context = await browser.new_context(
            user_agent=SABIT_USER_AGENT,
            viewport={"width": 1280, "height": 720}
        )
        page = await context.new_page()

        gecerli_kanal_adi = "Bilinmeyen Kanal"
        gecerli_logo_url = ""
        yakalananlar = set()
        link_yakalandi_olayi = asyncio.Event()

        # Performansı korumak için reklam ve gereksiz medya isteklerini engelliyoruz
        async def trafik_filtresi(route, request):
            if request.resource_type in ["stylesheet", "font"] or any(x in request.url for x in ["google", "analytics", "doubleclick"]):
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", trafik_filtresi)

        # Dinamik .m3u8 yakalama mekanizması
        async def istek_dinle(request):
            nonlocal gecerli_kanal_adi, gecerli_logo_url
            url = request.url
            if ".m3u8" in url and url not in yakalananlar:
                # Reklam veya istatistik servislerini eliyoruz
                if not any(x in url.lower() for x in ["analytics", "ads", "stat", "telemetry", "logger"]):
                    # Yayın sunucusunun kendi domainini (örneğin cfd uzantılı olanı) referer yapmak için regex kullanıyoruz
                    domain_match = re.search(r"https://[a-zA-Z0-9.-]+\.(cfd|com|net|xyz|club)", url)
                    referer = domain_match.group(0) + "/" if domain_match else f"{hedef_url}/"
                    
                    m3u_listesine_ekle(url, gecerli_kanal_adi, gecerli_logo_url, referer, CIKTI_DOSYASI)
                    yakalananlar.add(url)
                    link_yakalandi_olayi.set()

        page.on("request", istek_dinle)

        try:
            print(f"[ZİYARET] {hedef_url} adresine gidiliyor...")
            await page.goto(hedef_url, wait_until="commit", timeout=60000)
            await page.wait_for_timeout(4000) # Sayfanın kendine gelmesi için bekleme

            # Gönderdiğiniz görsele göre doğrudan "channel-item" sınıfına sahip a etiketlerini buluyoruz
            kanal_kutulari = await page.query_selector_all("a.channel-item")
            total_kanal = len(kanal_kutulari)
            print(f"📺 Sitede {total_kanal} adet kanal tespit edildi.")

            for index in range(total_kanal):
                try:
                    # Sayfa her değiştiğinde DOM elementlerini tazelemek için tekrar sorguluyoruz
                    güncel_kutular = await page.query_selector_all("a.channel-item")
                    if index >= len(güncel_kutular):
                        break
                        
                    kutu = güncel_kutular[index]
                    
                    # 1. KANAL ADINI AYIKLA (içindeki .channel-name div'inin text bilgisini alıyoruz)
                    kanal_adi_element = await kutu.query_selector(".channel-name")
                    if kanal_adi_element:
                        kanal_metni = await kanal_adi_element.inner_text()
                        gecerli_kanal_adi = kanal_metni.strip()
                    else:
                        # Eğer alt div henüz render olmadıysa href parametresindeki id değerini kullanalım
                        href_val = await kutu.get_attribute("href")
                        # id=b3 kısmından b3'ü çeker
                        id_match = re.search(r"id=([^&]+)", href_val) if href_val else None
                        gecerli_kanal_adi = id_match.group(1).upper() if id_match else f"Kanal_{index + 1}"

                    # 2. KANAL LOGOSUNU AYIKLA (Varsa img src yoksa boş bırakır)
                    gecerli_logo_url = ""
                    img_element = await kutu.query_selector("img")
                    if img_element:
                        src_attr = await img_element.get_attribute("src")
                        if src_attr:
                            if src_attr.startswith("/"):
                                gecerli_logo_url = f"{hedef_url}{src_attr}"
                            else:
                                gecerli_logo_url = src_attr

                    print(f"🔄 [{index + 1}/{total_kanal}] Tetikleniyor -> {gecerli_kanal_adi}")
                    link_yakalandi_olayi.clear()
                    
                    await kutu.scroll_into_view_if_needed()
                    await kutu.click(force=True) # Java tetikleyiciyi çalıştırmak için butona tıklıyoruz
                    
                    try:
                        # Tıklamadan sonra .m3u8 linkinin ağa düşmesini maksimum 8 saniye bekle
                        await asyncio.wait_for(link_yakalandi_olayi.wait(), timeout=8.0)
                    except asyncio.TimeoutError:
                        print(f"⚠️ {gecerli_kanal_adi} için link yakalanamadı (Süre aşımı).")
                    
                    # Sayfayı eski haline getirip döngüye devam et
                    await page.goto(hedef_url, wait_until="commit")
                    await page.wait_for_timeout(2000)

                except Exception as ex:
                    print(f"Kanal adımı atlanıyor: {ex}")
                    continue

            print(f"\n🏁 Otomasyon başarıyla tamamlandı. '{CIKTI_DOSYASI}' dosyası güncellendi!")

        except Exception as e:
            print(f"❌ Kritik Hata: {e}")
            sys.exit(1)
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
