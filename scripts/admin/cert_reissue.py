"""
Перевыпуск сертификата сервера под все адреса, по которым к нему ходят.

ЗАЧЕМ. Сертификат был выписан на один адрес — 192.168.0.184. Пока
роутер выдаёт Mac'у тот же IP, всё работает. Как только адрес
сменился (перезагрузили роутер, переехали на другую сеть, Wi-Fi вместо
кабеля) — защищённый адрес перестаёт открываться СРАЗУ НА ВСЕХ
устройствах: телефоны, ноутбуки, компьютеры цеха. И вместе с ним
пропадают уведомления и диктофон, которые без https не работают.

ЧТО ДЕЛАЕТ. Берёт все текущие адреса этого компьютера и сетевое имя
(alibeks-macbook-air.local) и перевыпускает сертификат сервера на них
разом. Корневой сертификат (ca.crt) НЕ трогается — его уже поставили
на телефоны, и переустанавливать ничего не нужно: устройства доверяют
центру, а не конкретной бумажке.

ЗАПУСК

    ./venv/bin/python scripts/admin/cert_reissue.py           # проверить
    ./venv/bin/python scripts/admin/cert_reissue.py --apply   # перевыпустить

Без --apply ничего не меняет: только говорит, чего не хватает.
С --apply перевыпускает и перезапускает https-сервер (иначе он будет
держать в памяти старую бумажку).

Проверка и перевыпуск идут сами раз в 15 минут — launchd-агент
com.acai.cert (scripts/admin/com.acai.cert.plist).
"""

import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CERTS = ROOT / "certs"
CA_CRT = CERTS / "ca.crt"
CA_KEY = CERTS / "ca.key"
SERVER_CRT = CERTS / "acai.crt"
SERVER_KEY = CERTS / "acai.key"
SERVER_CNF = CERTS / "server.cnf"

# Сколько живёт бумажка сервера. Меньше десяти лет намеренно: у Apple
# ограничение на срок серверного сертификата, слишком длинный Safari
# не принимает даже от доверенного центра.
DAYS = 800


def run(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, **kwargs)


def local_addresses() -> list:
    """Все адреса этого компьютера в локальной сети."""
    found = []

    result = run(["ifconfig"])
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line.startswith("inet "):
            continue
        address = line.split()[1]
        if address.startswith("127.") or address.startswith("169.254."):
            continue
        if address not in found:
            found.append(address)

    return found


def local_names() -> list:
    """Сетевые имена: по ним можно ходить, даже когда IP сменился."""
    names = ["localhost"]

    result = run(["scutil", "--get", "LocalHostName"])
    host = (result.stdout or "").strip()
    if host:
        names.append(f"{host}.local")

    # Короткое имя для ярлыков и для тех, кто не помнит цифры.
    names.append("acai.local")

    try:
        fqdn = socket.gethostname()
        if fqdn and fqdn not in names:
            names.append(fqdn)
            if not fqdn.endswith(".local"):
                names.append(f"{fqdn}.local")
    except OSError:
        pass

    # без повторов, порядок сохраняем
    return list(dict.fromkeys(names))


def current_san() -> set:
    """Что уже записано в действующем сертификате."""
    if not SERVER_CRT.exists():
        return set()
    result = run(["openssl", "x509", "-in", str(SERVER_CRT), "-noout", "-text"])
    text = result.stdout
    if "Subject Alternative Name" not in text:
        return set()
    lines = text.splitlines()
    index = next(i for i, line in enumerate(lines) if "Subject Alternative Name" in line)
    values = lines[index + 1].strip()
    # openssl печатает «IP Address:192.168.0.184», а в конфиг пишется
    # «IP:192.168.0.184» — без этого сверка всегда считала бы, что
    # адресов не хватает, и перевыпускала бумажку каждые 15 минут.
    return {
        part.strip().replace("IP Address:", "IP:")
        for part in values.split(",") if part.strip()
    }


def expires_in_days() -> int | None:
    if not SERVER_CRT.exists():
        return None
    result = run(["openssl", "x509", "-in", str(SERVER_CRT), "-noout", "-enddate"])
    raw = (result.stdout or "").strip().replace("notAfter=", "")
    try:
        end = datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z")
    except ValueError:
        return None
    return (end - datetime.now()).days


def wanted_san(addresses, names) -> list:
    return [f"IP:{a}" for a in addresses] + ["IP:127.0.0.1"] + [f"DNS:{n}" for n in names]


def reissue(addresses, names) -> None:
    if not (CA_CRT.exists() and CA_KEY.exists()):
        raise SystemExit("Нет корневого сертификата (certs/ca.crt, certs/ca.key) — перевыпускать нечем.")

    san = ", ".join(wanted_san(addresses, names))
    main_name = addresses[0] if addresses else "localhost"

    SERVER_CNF.write_text(
        "[req]\n"
        "distinguished_name = dn\n"
        "prompt = no\n"
        "[dn]\n"
        f"CN = {main_name}\n"
        "O = Astana Ceramic\n"
        "[v3]\n"
        f"subjectAltName = {san}\n"
        "basicConstraints = critical, CA:FALSE\n"
        "keyUsage = critical, digitalSignature, keyEncipherment\n"
        "extendedKeyUsage = serverAuth\n"
        "authorityKeyIdentifier = keyid\n"
        "subjectKeyIdentifier = hash\n",
        encoding="utf-8",
    )

    request = CERTS / "acai.csr"

    # Ключ сервера не меняем, если он уже есть: перевыпуск не должен
    # требовать ничего от устройств.
    if not SERVER_KEY.exists():
        result = run(["openssl", "genrsa", "-out", str(SERVER_KEY), "2048"])
        if result.returncode:
            raise SystemExit(f"Не удалось создать ключ: {result.stderr[:300]}")
        SERVER_KEY.chmod(0o600)

    result = run([
        "openssl", "req", "-new", "-key", str(SERVER_KEY),
        "-out", str(request), "-config", str(SERVER_CNF),
    ])
    if result.returncode:
        raise SystemExit(f"Не удалось составить запрос: {result.stderr[:300]}")

    result = run([
        "openssl", "x509", "-req", "-in", str(request),
        "-CA", str(CA_CRT), "-CAkey", str(CA_KEY), "-CAcreateserial",
        "-out", str(SERVER_CRT), "-days", str(DAYS), "-sha256",
        "-extfile", str(SERVER_CNF), "-extensions", "v3",
    ])
    if result.returncode:
        raise SystemExit(f"Не удалось подписать: {result.stderr[:300]}")

    request.unlink(missing_ok=True)


def restart_https() -> str:
    uid = run(["id", "-u"]).stdout.strip()
    result = run(["launchctl", "kickstart", "-k", f"gui/{uid}/com.acai.server.https"])
    return "перезапущен" if result.returncode == 0 else f"перезапустить не вышло: {result.stderr.strip()[:200]}"


def main() -> int:
    apply = "--apply" in sys.argv

    addresses = local_addresses()
    names = local_names()
    have = current_san()
    want = set(wanted_san(addresses, names))
    missing = want - have
    days_left = expires_in_days()

    print("Адреса этого компьютера:", ", ".join(addresses) or "нет")
    print("Сетевые имена:", ", ".join(names))
    print("В сертификате сейчас:", ", ".join(sorted(have)) or "ничего")
    if days_left is not None:
        print(f"Срок действия: ещё {days_left} дн.")

    stale = days_left is not None and days_left < 30

    if not missing and not stale:
        print("\nВсё на месте — перевыпускать нечего.")
        return 0

    if missing:
        print("\nНе хватает:", ", ".join(sorted(missing)))
    if stale:
        print("\nСрок подходит к концу — пора перевыпустить.")

    if not apply:
        print("Это проверка. Чтобы перевыпустить: добавьте --apply")
        return 1

    reissue(addresses, names)
    print("\nСертификат сервера перевыпущен:", ", ".join(sorted(current_san())))
    print("Корневой сертификат не менялся — на телефонах и ноутбуках ничего переустанавливать не нужно.")
    print("HTTPS-сервер:", restart_https())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
