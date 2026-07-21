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

def get_active_taraftarium_url(start_num, max_attempts=15):
    headers = {'User-Agent': SABIT_USER_AGENT}
    print("🌐 [ADIM 1] Aktif Taraftarium domaini aranıyor...")
    
    for i in range(max_attempts):
        current_num = start_num + i
        test_url = f"https://taraftarium{current_num}.xyz"
        print(f"🔎 {test_url} test ediliyor...")
        try:
            response = requests.get(test_url, headers=headers, timeout=4)
            if response.status_code == 200:
                print(f"✅ AKTİF DOMAİN BULUNDU: {test_url}")
                return test_url
        except requests.RequestException:
            continue
            
    print("⚠️ Aktif yeni domain bulunamadı! Başlangıç adresiyle devam ediliyor.")
    return f"https://taraftarium{start_num}.xyz"

def m3u_temizle_ve_hazirla(dosya_yolu):
    with open(dosya_yolu, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
    print(f"🧹 {dosya_yolu} temizlendi ve yeni kayıtlar için hazırlandı.")

def m3u_listesine_ekle(url, kanal_adi, referer_url, dosya_yolu):
    if not referer_url.endswith('/'):
        referer_url += '/'
        
    # Eski/hatalı dizin yapısını güncel yol ile değiştiriyoruz
    if "/ex1/" in url:
        url = url.replace("/ex1/", "/taraftarium/")
        
    with open(dosya_yolu, "a", encoding="utf-8") as f:
        f.write(f'#EXTINF:-1,{kanal_adi}\n')
        f.write(f'#EXTVLCOPT:http-referrer={referer_url}\n')
        f.write(f'#EXTVLCOPT:http-user-agent={SABIT_USER_AGENT}\n')
        f.write(f"{url}\n\n")
    print(f"💾 [KAYDEDİLDİ] {kanal_adi} -> M3U formatında yazıldı.")

async def main():
    hedef_url = get_active_taraftarium_url(BASLANGIC_DOMAIN_NUM)
    m3u_temizle_ve_hazirla(CIKTI_DOSYASI)
    
    async with async_playwright() as p:
        print("🚀 [ADIM 2] Playwright (Chromium) başlatılıyor...")
        browser = await p.chromium.launch(headless=True) 
        
        context = await browser.new_context(
            user_agent=SABIT_USER_AGENT,
            viewport={"width": 1280, "height": 720}
        )
        page = await context.new_page()

        async def trafik_filtresi(route, request):
            if request.resource_type in ["stylesheet", "font", "image"] or any(x in request.url for x in ["google", "analytics", "doubleclick", "adnxs"]):
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", trafik_filtresi)

        print(f"🛰️ [ADIM 3] Ana menü taranıyor: {hedef_url}")
        try:
            await page.goto(hedef_url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
        except Exception as e:
            print(f"❌ Ana sayfaya erişim başarısız (Süre aşımı): {e}")
            await browser.close()
            return

        kanal_elementleri = await page.query_selector_all("a.channel-item")
        kesfedilen_kanallar = []

        for kutu in kanal_elementleri:
            href = await kutu.get_attribute("href")
            id_match = re.search(r"id=([^&]+)", href) if href else None
            
            if id_match:
                kanal_id = id_match.group(1)
                kanal_adi_element = await kutu.query_selector(".channel-name")
                if kanal_adi_element:
                    kanal_adi = (await kanal_adi_element.inner_text()).strip()
                else:
                    kanal_adi = f"Kanal {kanal_id.upper()}"
                
                # ATV kanalını listeden muaf tutuyoruz
                if "atv" in kanal_adi.lower() or "atv" in kanal_id.lower():
                    print(f"⏭️ [ATLANTI] {kanal_adi} (ATV listeden çıkarıldı)")
                    continue

                kesfedilen_kanallar.append({"id": kanal_id, "name": kanal_adi})

        total_kanal = len(kesfedilen_kanallar)
        print(f"📺 Toplam {total_kanal} kanal tespit edildi. Tarama başlıyor...\n")

        if total_kanal == 0:
            print("❌ HATA: Sitede uygun kanal elemanı bulunamadı!")
            await browser.close()
            return

        for index, kanal in enumerate(kesfedilen_kanallar):
            kanal_id = kanal["id"]
            kanal_adi = kanal["name"]
            
            kanal_sayfa_url = f"{hedef_url}/channel.html?id={kanal_id}"
            print(f"\n⚡ [{index + 1}/{total_kanal}] Tarama: {kanal_adi} (ID: {kanal_id})")
            print(f"   -> Sayfaya gidiliyor: {kanal_sayfa_url}")

            yakalanan_url = None
            link_yakalandi_olayi = asyncio.Event()

            async def istek_dinle(request):
                nonlocal yakalanan_url
                url = request.url
                # .m3u8 uzantılı yayın isteklerini yakalar
                if re.search(r"\.m3u8(\?|$)", url):
                    yakalanan_url = url
                    link_yakalandi_olayi.set()

            page.on("request", istek_dinle)

            try:
                await page.goto(kanal_sayfa_url, wait_until="domcontentloaded", timeout=10000)
                
                try:
                    await asyncio.wait_for(link_yakalandi_olayi.wait(), timeout=6.0)
                except asyncio.TimeoutError:
                    pass

                if yakalanan_url:
                    print(f"   🎯 LINK BULUNDU: {yakalanan_url}")
                    m3u_listesine_ekle(yakalanan_url, kanal_adi, hedef_url, CIKTI_DOSYASI)
                else:
                    print(f"   ⚠️ Yayın linki bu kanal için yakalanamadı.")

            except Exception as ex:
                print(f"   ❌ Sayfa yüklenirken hata oluştu: {str(ex)[:50]}")
            finally:
                page.remove_listener("request", istek_dinle)

        print(f"\n🏁 [BİTTİ] '{CIKTI_DOSYASI}' dosyası başarıyla güncellendi!")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
