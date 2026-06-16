# 🤖 ESP32-CAM Otonom Güvenlik Botu (Görüntü İşleme ve Takip Sistemi)

Bu proje, **ESP32-CAM** tabanlı, etrafı 180 derece tarayabilen ve Python üzerinde çalışan bir OpenCV yazılımı ile "Kırmızı ve Dairesel" tehlikeli nesneleri otonom olarak tespit eden akıllı bir güvenlik sistemidir. Arduino IDE ve Python kullanılarak geliştirilmiştir.

## 🎯 Özellikler
- **Wi-Fi Görüntü Aktarımı**: ESP32-CAM üzerinden bilgisayara düşük gecikmeli, kablosuz JPEG görüntü aktarımı.
- **Otonom 180 Derece Tarama**: Radar mantığıyla çalışan SG90 servo motor ile sürekli alan taraması (500us - 2500us arası tam 180 derece tarama).
- **Akıllı Görüntü Analizi**: Görüntüdeki kırmızı, dairesel (yuvarlaklık oranı yüksek) nesnelerin OpenCV ile algılanması ve hedefe kilitlenme.
- **Alarm Sistemi**: Tehlike (hedef) algılandığında veya manuel olarak tetiklendiğinde çalışan Buzzer sistemi ve hedefe dönük şekilde kilitlenen servo motor.
- **Uzaktan Debug (Hata Ayıklama)**: ESP32'nin C++ arka plan loglarını USB kablosuna ihtiyaç duymadan kablosuz (HTTP `/log` üzerinden) doğrudan Python konsoluna aktarabilme.
- **Çift Modlu Çalışma**: 
  - *Otonom Mod*: Sistem kendini tarar, hedefini arar.
  - *Manuel Mod*: Analiz devre dışı bırakıldığında `Z` ve `X` tuşları ile servo motor bilgisayardan kontrol edilebilir, flaş ve siren açılıp kapatılabilir.

## 🛠️ Kullanılan Donanım Parçaları
- 1 adet **ESP32-CAM Modülü** (Kamera kartı)
- 1 adet **SG90 Servo Motor** (Radar taraması için)
- 1 adet **Buzzer** (Alarm/Siren için)
- Jumper kablolar ve Güç Kaynağı (Batarya veya 5V adaptör)

### Devre / Pin Bağlantıları
| Bileşen | ESP32-CAM Pini | Görevi |
| --- | --- | --- |
| **Buzzer** | `GPIO 14` | Tehlike anında sesli ikaz |
| **Servo Motor** | `GPIO 15` | Kamera yönlendirmesi (180 derece) |
| **Dahili Flaş LED**| `GPIO 4` | Gece görüşü için aydınlatma (Modül üzerinde mevcut) |

---

## 🧠 Çalışma Mantığı ve Algoritma

Sistem iki ana parçadan oluşur: **ESP32-CAM (Sunucu)** ve **Python Analiz Scripti (İstemci)**.

### 1. ESP32-CAM (C++ / Arduino) Algoritması
ESP32, bir Web Sunucusu (HTTP Server) oluşturarak yerel ağda yayın yapar. 
- **Çoklu Uç Noktalar (Endpoints)**: `/stream` ile videoyu aktarır, `/servo`, `/alarm`, `/scan`, `/control`, ve `/log` ile gelen komutları anında donanıma yansıtır.
- **Asenkron Motor Kontrolü**: `loop()` fonksiyonu içinde `delay()` kullanmadan (adım gecikmeleri ile bloklama yapmadan), servoyu çevirerek "radar" taramasını yapar. Eğer Python tarafından alarm veya "manuel mod" sinyali gelirse (`auto_scan_state = false`), motor otomatik taramayı anında keser.
- **Donanımsal PWM**: Servo kontrolleri için ESP32'nin donanımsal `ledc` kütüphanesi (50Hz sinyal) kullanılır.

### 2. Python OpenCV (Görüntü İşleme) Algoritması
Görüntüler ağ üzerinden alınır ve bir sonsuz döngü içerisinde kare kare (`frame`) işlenir:
1. **Renk Filtreleme (HSV)**: Görüntü BGR formatından HSV (Ton, Doygunluk, Parlaklık) formatına çevrilir. Sadece kırmızı renk aralığına uygun olan pikselleri ayırmak için bir maske (`cv2.inRange`) oluşturulur.
2. **Gürültü Temizleme (Filtreleme)**: Oluşan maskeye medyan filtresi (`cv2.medianBlur`) uygulanarak sensör kirliliğinden kaynaklanan ufak parazitler silinir.
3. **Kontur Bulma ve Geometrik Analiz**: Filtrelenmiş maskede kalan adacıkların (konturların) alan ve çevre uzunluğu hesaplanır (`cv2.arcLength` ve `cv2.contourArea`).
4. **Dairesellik Formülü**: `(4 * π * Alan) / (Çevre²)` formülü kullanılarak nesnenin ne kadar yuvarlak olduğu bulunur. Bu oran %70'in üzerindeyse ve alan çok küçük değilse (yanılsama değilse), hedefin etrafına yeşil çember ve merkezine kırmızı nişangah çizilir.
5. **Aksiyon Alma**: Hedef tespit edildiği an ESP32'ye HTTP isteği ile Alarm komutu gönderilir. Motor taramayı durdurup hedefe kilitlenir.

---

## 🚀 Kurulum ve Kullanım

### Adım 1: ESP32-CAM Kodunun Yüklenmesi
1. Arduino IDE üzerinden `CameraWebServer.ino` dosyasını açın.
2. Kod içerisindeki Wi-Fi adı (`ssid`) ve şifrenizi (`password`) kendi ağınıza göre değiştirin.
3. ESP32-CAM kartınıza FTDI (USB to TTL) programlayıcı kullanarak kodu yükleyin.
4. Serial Monitörü açarak ESP32'nin aldığı IP adresini not edin.

### Adım 2: Python Scriptinin Hazırlanması
Bilgisayarınızda Python yüklü olmalıdır. Gerekli kütüphaneleri kurmak için terminali/CMD'yi açıp şu komutu girin:
```bash
pip install opencv-python numpy requests
```

### Adım 3: Çalıştırma
1. `guvenlik_analiz.py` dosyasını bir metin editörü ile açın.
2. 11. satırdaki `esp32_ip = '...'` kısmına, Arduino IDE'de not ettiğiniz IP adresini yazın.
3. ESP32'nize pilden veya adaptörden güç verin. Bilgisayara bağlı olmasına gerek yoktur.
4. Terminal üzerinden Python scriptini çalıştırın:
```bash
python guvenlik_analiz.py
```

### 🎮 Klavye Kısayolları (Kontrol Merkezi)
Video penceresi aktifken aşağıdaki tuşları kullanarak sisteme müdahale edebilirsiniz:
- **`A` Tuşu:** Otonom Tarama ve Analizi Açar/Kapatır. (Kapatıldığında manuel moda geçer).
- **`Z` ve `X` Tuşları:** Manuel moddayken servoyu Sağa ve Sola döndürür.
- **`S` Tuşu:** Alarm/Sireni manuel olarak tetikler.
- **`F` Tuşu:** Kamera üzerindeki Flaş LED'i açıp kapatır.
- **`Q` Tuşu:** Güvenli şekilde sistemi durdurur ve çıkar.

---

*Bu proje güvenlik ve otomasyon algoritmalarını donanım gücüyle birleştirmek üzere geliştirilmiştir.*
