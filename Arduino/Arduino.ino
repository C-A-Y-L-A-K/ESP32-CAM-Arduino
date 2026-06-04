#include <Servo.h>

// --- PİN VE NESNE TANIMLAMALARI ---
Servo kameraServo;
const int buzzerPin = 8;     // Alarm sireni için Buzzer 8. pinde
const int servoPin = 9;      // Kamera Servo motoru 9. pinde

// --- DEVRİYE VE ZAMANLAMA DEĞİŞKENLERİ ---
int servoAcisi = 90;         // Başlangıç açısı (Tam karşı)
int servoYon = 1;            // 1: Sağa dönüyor, -1: Sola dönüyor
unsigned long eskiZaman = 0;  // Servo hareket zamanlaması için (delay kullanmamak için)
const int taramaHizi = 30;   // Servonun her adım arasındaki bekleme süresi (ms) - Küçüldükçe hızlanır

void setup() {
  Serial.begin(9600);        // Python (guvenlik_analiz.py) ile haberleşme hızı
  
  pinMode(buzzerPin, OUTPUT);
  
  kameraServo.attach(servoPin); 
  kameraServo.write(servoAcisi); // Servoyu merkeze çek
  
  // Python terminalinde bağlantı sağlandığında görünecek ilk selamlama logu
  Serial.println("[ARDUINO LOG]: Sistem Hazir, Caylak! Komutlar bekleniyor...");
}

void loop() {
  // Sistemde o an alarm olup olmadığını tutan kontrol değişkeni
  boolean alarmVar = false;

  // 1. ADIM: PYTHON'DAN GELEN EMİRLERİ KONTROL ET
  if (Serial.available() > 0) {
    char gelenVeri = Serial.read(); // Python'dan gelen tek karakterlik veriyi oku
    
    if (gelenVeri == '1') { 
      alarmVar = true;  // Python hedefi gördü veya manuel alarm verdi!
    } else if (gelenVeri == '0') {
      alarmVar = false; // Ortam güvenli
    }
  }

  // 2. ADIM: DURUMA GÖRE SİSTEMİ YÖNET (ALARM VS DEVRİYE)
  if (alarmVar) {
    // --- HEDEFE KİLİTLENME VE SİREN MODU ---
    // Servo motor devriyeyi durdurur (olduğu açıda kilitlenir).
    
    // Güçlü ve dikkat çekici kesikli polis sireni tonu üretimi
    tone(buzzerPin, 3500); 
    delay(80);
    tone(buzzerPin, 2500);
    delay(80);
    
  } else {
    // --- OTONOM DEVRİYE TARAMA MODU ---
    noTone(buzzerPin); // Siren susturulur
    
    // delay() fonksiyonu kullanmıyoruz çünkü delay koyarsak Python'dan gelen 
    // anlık komutları Arduino kaçırabilir. "millis()" ile akıllı zamanlama yapıyoruz:
    unsigned long suankiZaman = millis();
    
    if (suankiZaman - eskiZaman >= taramaHizi) {
      eskiZaman = suankiZaman; // Zamanı güncelle
      
      servoAcisi += servoYon; // Açıyı yöne göre 1 derece artır veya azalt
      
      // Sınır kontrolü: 30 ile 150 derece arasında git-gel yap (Kamera kabloları zorlanmasın diye)
      if (servoAcisi >= 150) {
        servoYon = -1; // Sola dönmeye başla
      } else if (servoAcisi <= 30) {
        servoYon = 1;  // Sağa dönmeye başla
      }
      
      kameraServo.write(servoAcisi); // Servoya yeni açıyı gönder
    }
  }
}