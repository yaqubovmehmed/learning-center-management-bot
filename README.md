# 🎓 Excellence LC — Telegram boshqaruv boti

O'quv markaz uchun yengil, xavfsiz va ko'p o'qituvchili Telegram bot.
O'quvchilar, patoklar, davomat, test/mock natijalari, ota-onalar bilan aloqa,
hisobotlar va audit — barchasi bitta botda.

- **Python 3.11+**, `aiogram 3`, `aiosqlite`
- Bitta SQLite fayl (WAL rejimi), avtomatik zaxira nusxa
- Ota-onalar va o'qituvchilar uchun bir martalik, telefon bilan tasdiqlanadigan taklif havolalari
- Fon rejimida xabar navbati (outbox), haftalik hisobot, kunlik backup
- Faqat shaxsiy chatda ishlaydi; bot guruhga qo'shilsa avtomatik chiqib ketadi

---

## 1. Tez ishga tushirish

Repository'dan olish:

```bash
git clone https://github.com/yaqubovmexmedjon/learning-center-management-bot.git
cd learning-center-management-bot
```

Windows:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
notepad .env
run.bat
```

Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
python main.py
```

### `.env` ni to'ldirish

| Kalit | Tavsif |
|---|---|
| `BOT_TOKEN` | @BotFather bergan token. **Hech kimga bermang.** |
| `SUPERADMIN_IDS` | Super admin(lar) Telegram ID si, vergul bilan |
| `BOOTSTRAP_CODE` | Ixtiyoriy: birinchi super adminni `/claim KOD` bilan ulash uchun |
| `SECRET_PEPPER` | Taklif tokenlari uchun sir. Bo'sh qolsa `.secret_pepper` fayli avtomatik yaratiladi |
| `DB_PATH` | Baza fayli (standart `data/excellence.db`) |
| `TIMEZONE` | Standart `Asia/Tashkent` |
| `DIGEST_WEEKDAY`, `DIGEST_HOUR` | Haftalik hisobot kuni/soati (0 = dushanba) |

> `SUPERADMIN_IDS` yoki `BOOTSTRAP_CODE` dan kamida bittasi **shart**.
> Telegram ID ni bilish uchun botga `/whoami` yozing yoki @userinfobot dan foydalaning.

### Birinchi kirish

1. Botni ishga tushiring: `run.bat` yoki `python main.py`.
2. Telegramda botga `/start` yozing.
3. Agar `SUPERADMIN_IDS` to'ldirilgan bo'lsa — darhol super admin sifatida kirasiz.
4. Aks holda `.env` dagi kod bilan: `/claim KOD`.
5. Kod ishlatilgach, xavfsizlik uchun `BOOTSTRAP_CODE` ni `.env` dan olib tashlang.

### BotFather sozlamalari

- **Inline rejim** (guruh jadvalini ulashish uchun): @BotFather → `/setinline` → botni tanlang →
  placeholder kiriting, masalan `IELTS guruhini qidirish...`
- Buyruqlar menyusi bot ishga tushganda avtomatik o'rnatiladi.
- Botni guruhga qo'shish shart emas — u guruhlarda ishlamaydi va darhol chiqib ketadi.

---

## 2. Rollar va imkoniyatlar

### 🛡 Superadmin
- Barcha admin imkoniyatlari
- Audit jurnalini tozalash, qo'lda zaxira nusxa yaratish
- O'qituvchini admin qilish
- Tizim sozlamalari

### 👨‍💼 Admin
- O'quvchilar: qo'shish, qidirish, tahrirlash, guruhga o'tkazish, holat, ota-ona biriktirish
- Patoklar: yaratish, o'qituvchi biriktirish, jadval, arxivlash
- Davomat: keldi / kechikdi / kelmadi / sababli, kirish-chiqish vaqti, izoh, dars mavzusi
- Testlar: test/mock/quiz/imtihon, tezkor ketma-ket ball kiritish, IELTS band, e'lon qilish
- Hisobotlar: davomat, test tahlili, xavf ostidagilar, o'qituvchilar yuklamasi, CSV
- Xabarlar markazi: navbat, nosozlarni qayta yuborish, ommaviy xabar
- Ota-onalardan kelgan sabab xabarlari
- Taklif havolalarini yaratish va bekor qilish

### 👨‍🏫 O'qituvchi
- Faqat o'ziga biriktirilgan patoklar va o'quvchilar
- Davomat va vaqt qayd etish
- Test yaratish, ball kiritish, natijalarni e'lon qilish
- O'z guruhlari bo'yicha hisobot
- Boshqa guruhlar, telefon raqamlari va moliyaviy ma'lumotlar yopiq

### 👨‍👩‍👧 Ota-ona
- Farzand(lar)i kartasi: davomat, jadval, oxirgi natija
- Oylik davomat tarixi
- Test natijalari va o'sish dinamikasi (foizda, sodda tilda)
- Sabab yuborish (o'qituvchi yoki adminga boradi)
- Xabar sozlamalari: kelmadi / kechikdi / natija / haftalik hisobot

---

## 3. Xavfsizlik

- **Faqat shaxsiy chat**: barcha handlerlar private chatda ishlaydi; bot guruhga qo'shilsa chiqib ketadi.
- **RBAC**: har bir amal oldidan rol va egalik tekshiriladi (`app/services/permissions.py`).
- **Taklif havolalari**: 32 bayt random token, bazada faqat HMAC-SHA256 hash; 72 soat; bir marta;
  telefon raqami Telegram `contact` orqali tasdiqlanadi.
- **Rate limit**: xabar va callback uchun alohida sirpanuvchi oyna; `/claim` uchun 5 urinish / 10 daqiqa.
- **Audit jurnali**: muhim amallar (`attendance_save`, `test_publish`, `student_edit`, `broadcast`, backup va h.k.).
- **HTML escaping**: foydalanuvchi kiritgan barcha matnlar `esc()` orqali chiqariladi.
- **CSV injection himoyasi**: `=`, `+`, `-`, `@` bilan boshlanuvchi kataklar neytrallashtiriladi.
- **Maxfiy ma'lumot**: tokenlar, pepper va baza `.gitignore` da; loglarga yozilmaydi.
- **Tranzaksiyalar**: o'quvchi + ota-ona, davomat, natijalar bir tranzaksiyada.
- **Zaxira**: VACUUM INTO orqali izchil nusxa; `integrity_check` tekshiruvi.

> Muhim: `.env`, `data/` va `.secret_pepper` fayllarini hech qachon ommaviy repoga qo'ymang.

---

## 4. Kundalik ish tartibi

1. **Patok yaratish**: 🗂 Patoklar → ➕ Yangi patok.
2. **O'qituvchi qo'shish**: 👨‍🏫 O'qituvchilar → ➕ Yangi o'qituvchi → taklif havolasini yuborish.
3. **O'quvchi qo'shish**: 👥 O'quvchilar → ➕ Yangi o'quvchi → ota-ona ismi va telefoni.
   Bot ota-ona uchun taklif havolasini beradi (nusxalash tugmasi bilan).
4. **Davomat**: ✅ Davomat → patok → o'quvchi ustiga bosib holatni almashtirish
   (✅ keldi → ❌ kelmadi → ⏰ kechikdi → 📝 sababli), 🕒 bilan aniq vaqt, 💾 Saqlash.
   Saqlashda kelmagan/kechikkanlar ota-onalariga avtomatik xabar navbatga qo'yiladi.
5. **Test**: 📝 Testlar → ➕ Yangi test → patok, nom, tur, sana, maksimal ball →
   ⚡️ tezkor kiritish yoki o'quvchi bo'yicha. So'ng 📢 e'lon qilish.
6. **Hisobot**: 📊 Hisobotlar → davomat / test tahlili / xavf ostidagilar / CSV.
7. **Haftalik hisobot**: avtomatik (sozlamalardagi kun/soat) yoki qo'lda yuborish.

---

## 5. Loyiha tuzilishi

```
learning-center-management-bot/
├─ main.py                 # kirish nuqtasi
├─ config.py               # .env, validatsiya, vaqt mintaqasi
├─ app/
│  ├─ bot.py               # bot/dispatcher, routerlar, middleware
│  ├─ db.py                # SQLite qatlami, tranzaksiya, backup
│  ├─ schema.sql           # to'liq sxema
│  ├─ security.py          # rate limit, token hash, audit
│  ├─ utils.py             # sana, telefon, IELTS, CSV himoyasi
│  ├─ keyboards.py, ui.py  # menyu va xabar yordamchilari
│  ├─ worker.py            # outbox worker, scheduler, backup
│  ├─ services/            # biznes logika (students, tests, reports, ...)
│  └─ handlers/            # Telegram handlerlari
├─ tests/smoke_test.py     # oflayn tekshiruv (token kerak emas)
├─ requirements.txt
├─ .env.example
├─ run.bat / run.sh
└─ Dockerfile, docker-compose.yml
```

---

## 6. Docker (ixtiyoriy)

```bash
copy .env.example .env
# .env ni to'ldiring
docker compose up -d --build
docker compose logs -f
```

Baza va zaxiralar `./data` papkasida saqlanadi (volume).

---

## 7. Tekshiruv va muammolarni bartaraf etish

Oflayn tekshiruv (Telegram tokeni kerak emas):

```bash
python tests/smoke_test.py
```

Natija: `✅ 61 tekshiruv muvaffaqiyatli o'tdi.`

| Muammo | Yechim |
|---|---|
| `BOT_TOKEN noto'g'ri` | `.env` dagi tokenni tekshiring, qo'shtirnoqsiz yozing |
| `Super admin yo'q` | `SUPERADMIN_IDS` yoki `BOOTSTRAP_CODE` qo'shing |
| Bot javob bermayapti | Bot tokeni boshqa joyda ishlab turgan bo'lishi mumkin (bir token — bitta instans) |
| Taklif havolasi ishlamaydi | BotFather da `/setinline` emas, bot username to'g'riligini tekshiring; havola 72 soat amal qiladi |
| Inline qidiruv bo'sh | BotFather → `/setinline` yoqilganini tekshiring; sozlamalarda `inline_public` yoniq bo'lsin |
| Xabar ketmayapti | 🔔 Xabarlar → ⚠️ Nosoz xabarlar; ota-ona botni bloklagan bo'lsa `skipped` bo'ladi |
| Baza shikastlangan | `data/backups/` dagi eng yangi nusxani `data/excellence.db` ga almashtiring |
| Vaqt noto'g'ri | `.env` da `TIMEZONE=Asia/Tashkent` |

Loglar: `logs/bot.log` (aylanuvchi, 1.5 MB × 3).

---

## 8. Cheklovlar

- Bitta bot tokeniga bitta instans (Telegram cheklovi).
- Inline rejim faqat guruh jadvalini ko'rsatadi — o'quvchi/ota-ona ma'lumotlari hech qachon ommaviy emas.
- FSM xotirada: bot qayta ishga tushsa, tugallanmagan forma bekor bo'ladi (ma'lumotlar bazaga yozilmaydi).
- Haftalik hisobot va backup bot ishlab turgan vaqtda bajariladi.

---

## 9. Litsenziya

MIT — `LICENSE` faylida. Muallif: Mexmedjon Yaqubov.

> ⚠️ `.env`, `.secret_pepper`, `data/` va `logs/` hech qachon repoga qo'shilmaydi
> (`.gitignore` da). Token yoki baza faylini tasodifan commit qilsangiz — tokenni
> @BotFather orqali darhol yangilang va tarixdan olib tashlang.
