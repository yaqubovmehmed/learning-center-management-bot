# 🎓 O'quv markaz uchun Telegram bot

O'quv markazni boshqarish uchun yengil Telegram bot. O'quvchilar, guruhlar,
davomat, test natijalari va ota-onalar bilan aloqa — hammasi bitta joyda.

Bot Python'da yozilgan, ma'lumotlar bitta SQLite faylida saqlanadi.
Qo'shimcha server yoki ma'lumotlar bazasi kerak emas.

---

## Nima qila oladi?

- **O'quvchilar** — qo'shish, qidirish, tahrirlash, guruhga biriktirish.
- **Guruhlar (patoklar)** — jadval, o'qituvchi, xona, to'lov, arxivlash.
- **Davomat** — keldi / kechikdi / kelmadi / sababli, kirish va chiqish vaqti.
- **Avtomatik xabar** — o'quvchi kelmasa yoki kechiksa, ota-onasiga darhol xabar boradi.
- **Testlar** — oddiy test, mock va imtihon. Ball kiritiladi, foiz va IELTS bahosi chiqadi.
- **Natija izohi** — ota-onaga oldingi natija bilan solishtirib, sodda tilda yoziladi
  (masalan: "o'tgan testdan 12% yaxshi").
- **Hisobotlar** — davomat, past natijali o'quvchilar, guruh kesimida, CSV fayl.
- **Haftalik hisobot** — har hafta ota-onalarga avtomatik xulosa.
- **Xavfsizlik** — har kim faqat o'z ishini ko'radi, barcha muhim amallar jurnalga yoziladi.

---

## Kim nima qiladi?

**🛡 Super admin** — hammasini boshqaradi. Admin qo'shadi, jurnal va zaxira nusxani ko'radi.

**👨‍💼 Admin** — o'quvchi, guruh va o'qituvchi qo'shadi, taklif havolasini yuboradi,
xabarlarni boshqaradi.

**👨‍🏫 O'qituvchi** — faqat o'z guruhlarini ko'radi. Davomat belgilaydi, test yaratadi,
ball kiritadi va natijani e'lon qiladi.

**👨‍👩‍👧 Ota-ona** — faqat o'z farzandini ko'radi. Davomat, jadval, natijalar va
sabab xabari yuborish imkoniyati bor.

---

## O'rnatish (3 qadam)

**1. Kodni olish**

```bash
git clone https://github.com/yaqubovmexmedjon/learning-center-management-bot.git
cd learning-center-management-bot
```

**2. Sozlamalar faylini yaratish**

Windows:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
notepad .env
```

Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
```

**3. Ishga tushirish**

```bat
run.bat
```

yoki `python main.py`.

---

## `.env` faylida nima yoziladi?

| Nomi | Nima uchun kerak |
|---|---|
| `BOT_TOKEN` | @BotFather bergan token. Bu — botning kaliti, hech kimga bermang. |
| `SUPERADMIN_IDS` | Sizning Telegram ID raqamingiz. Bir nechta bo'lsa vergul bilan. |
| `BOOTSTRAP_CODE` | Ixtiyoriy. Birinchi adminni `/claim KOD` bilan ulash uchun. |
| `SECRET_PEPPER` | Taklif havolalarini himoyalash uchun sir. Bo'sh qolsa, bot o'zi yaratadi. |
| `DB_PATH` | Ma'lumotlar bazasi fayli. Standart: `data/excellence.db`. |
| `TIMEZONE` | Vaqt mintaqasi. Standart: `Asia/Tashkent`. |
| `DIGEST_WEEKDAY`, `DIGEST_HOUR` | Haftalik hisobot kuni va soati (0 = dushanba). |

`SUPERADMIN_IDS` yoki `BOOTSTRAP_CODE` — kamida bittasi bo'lishi shart,
aks holda botga hech kim admin sifatida kira olmaydi.

Telegram ID'ingizni bilish uchun botga `/whoami` yozing.

---

## Birinchi kirish

1. Botni ishga tushiring.
2. Telegramda botga `/start` yozing.
3. `SUPERADMIN_IDS` to'ldirilgan bo'lsa — darhol admin sifatida kirasiz.
4. Aks holda: `/claim KOD` (kod `.env` dagi `BOOTSTRAP_CODE`).
5. Kod ishlatilgandan keyin uni `.env` dan o'chirib qo'ying.

### @BotFather'da nima qilish kerak

- **Inline rejim** (guruh jadvalini ulashish uchun): `/setinline` → botni tanlang →
  masalan `IELTS guruhini qidirish...` deb yozing.
- Buyruqlar menyusi bot ishga tushganda o'zi o'rnatiladi.
- Botni guruhga qo'shish shart emas — u faqat shaxsiy chatda ishlaydi.

---

## Kundalik ishlatish

1. **Guruh yaratish** — 🗂 Guruhlar → ➕ Yangi guruh.
2. **O'qituvchi qo'shish** — 👨‍🏫 O'qituvchilar → ➕ → taklif havolasini yuborish.
3. **O'quvchi qo'shish** — 👥 O'quvchilar → ➕ → ism, telefon, ota-ona telefoni.
   Bot ota-ona uchun taklif havolasini beradi (nusxalash tugmasi bilan).
4. **Davomat** — ✅ Davomat → guruh → o'quvchi ustiga bosib holatni almashtirish →
   💾 Saqlash. Saqlanganda kelmaganlar ota-onasiga xabar ketadi.
5. **Test** — 📝 Testlar → ➕ → guruh, nom, tur, maksimal ball → ballarni kiritish →
   📢 E'lon qilish. Faqat e'lon qilingan natijani ota-ona ko'radi.
6. **Hisobot** — 📊 Hisobotlar → davomat, xavf ostidagilar, CSV.

---

## Xavfsizlik

- Bot faqat **shaxsiy chatda** ishlaydi. Guruhga qo'shilsa, o'zi chiqib ketadi.
- Har bir amalda **rol tekshiriladi**: o'qituvchi boshqa guruhni, ota-ona boshqa
  bolani ko'ra olmaydi.
- **Taklif havolasi** bir marta ishlaydi, 72 soat amal qiladi. Bazada faqat
  shifrlangan ko'rinishi saqlanadi.
- Telefon raqami Telegram'ning **kontakt** tugmasi orqali tasdiqlanadi.
- **Rate limit** — kimdir botni ko'p urib yuborsa, vaqtincha to'xtatiladi.
- **Audit jurnali** — kim, qachon, nima qilgani saqlanadi.
- **CSV himoyasi** — Excel formulalari orqali zarar yetkazishning oldi olinadi.
- Token, baza va `.secret_pepper` fayli repoga tushmaydi.

> Muhim: `.env`, `data/` va `.secret_pepper` fayllarini hech kim bilan
> bo'lishmang va ommaviy joyga qo'ymang.

---

## Ma'lumotlar qayerda saqlanadi?

| Nima | Qayerda |
|---|---|
| Baza | `data/excellence.db` |
| Zaxira nusxa | `data/backups/` (har kuni, 14 kun saqlanadi) |
| Loglar | `logs/bot.log` |

Zaxira nusxa har kuni soat 03:00 da avtomatik olinadi.
Baza buzilsa, eng yangi nusxani `data/excellence.db` ga almashtirish kifoya.

---

## Tekshirish

Telegram tokeni kerak emas — hammasi oflayn tekshiriladi:

```bash
python tests/smoke_test.py
```

Natija: `✅ 61 tekshiruv muvaffaqiyatli o'tdi.`

Har push'da GitHub'da avtomatik tekshiruv (`.github/workflows/tests.yml`) ishlaydi.

---

## Docker (ixtiyoriy)

```bash
copy .env.example .env
# .env ni to'ldiring
docker compose up -d --build
docker compose logs -f
```

Baza va zaxiralar `./data` papkasida qoladi.

---

## Loyiha tuzilishi

```
learning-center-management-bot/
├─ main.py                 # botni ishga tushirish
├─ config.py               # .env sozlamalari
├─ app/
│  ├─ bot.py               # bot va routerlar
│  ├─ db.py                # SQLite bilan ishlash
│  ├─ schema.sql           # jadval tuzilishi
│  ├─ security.py          # xavfsizlik, audit
│  ├─ utils.py             # yordamchi funksiyalar
│  ├─ keyboards.py, ui.py  # tugmalar va xabarlar
│  ├─ worker.py            # xabar navbati, scheduler
│  ├─ services/            # biznes logika
│  └─ handlers/            # Telegram handlerlari
├─ tests/                  # oflayn tekshiruvlar
└─ Dockerfile, docker-compose.yml, run.bat, run.sh
```

---

## Muammolar va yechimlari

| Muammo | Yechim |
|---|---|
| `BOT_TOKEN noto'g'ri` | `.env` dagi tokenni tekshiring, qo'shtirnoqsiz yozing |
| `Super admin yo'q` | `SUPERADMIN_IDS` yoki `BOOTSTRAP_CODE` qo'shing |
| Bot javob bermayapti | Token boshqa joyda ishlab turgan bo'lishi mumkin — bir tokenga bitta bot |
| Taklif havolasi ishlamaydi | Havola 72 soat amal qiladi; bot username to'g'riligini tekshiring |
| Inline qidiruv bo'sh | @BotFather'da `/setinline` yoqilganini tekshiring |
| Xabar ketmayapti | 🔔 Xabarlar → ⚠️ Nosoz xabarlar. Ota-ona botni bloklagan bo'lishi mumkin |
| Baza buzilgan | `data/backups/` dagi eng yangi nusxani almashtiring |
| Vaqt noto'g'ri | `.env` da `TIMEZONE=Asia/Tashkent` |

---

## Cheklovlar

- Bitta tokenga bitta bot — bir vaqtda faqat bitta nusxa ishlaydi.
- Inline rejim faqat guruh jadvalini ko'rsatadi. O'quvchi va ota-ona ma'lumotlari
  hech qachon ommaviy ko'rinmaydi.
- Tugallanmagan forma bot qayta ishga tushsa bekor bo'ladi.
- Haftalik hisobot va zaxira nusxa bot ishlab turgan vaqtda bajariladi.

---

Litsenziya: MIT (`LICENSE` faylida).
