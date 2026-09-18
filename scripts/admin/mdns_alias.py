"""
Постоянное имя сайта в заводской сети: acai.local

ЗАЧЕМ. Цифры адреса (192.168.0.184) никто не помнит, а главное — они
меняются, когда роутер выдаёт новый IP: тогда перестают открываться
закладки на телефонах и ярлыки на компьютерах. Имя acai.local не
меняется никогда — телефон, ноутбук и компьютер в цеху спрашивают
«кто такой acai.local» прямо в сети, и этот Mac отвечает.

КАК. macOS умеет публиковать имя через Bonjour (dns-sd -P) — без прав
администратора и не трогая имя самого компьютера.

Адрес берётся при каждом запуске заново, поэтому после смены IP хватит
перезапуска агента:

    launchctl kickstart -k gui/$(id -u)/com.acai.mdns

Запускается агентом com.acai.mdns и держится в памяти (KeepAlive).
Написано на Python, а не на bash, намеренно: launchd не пускает
/bin/bash в папку Documents (macOS требует для этого разрешение на
«полный доступ к диску»), а venv/bin/python туда ходит — им же
запускаются остальные агенты ACAI.
"""

import os
import subprocess
import sys
from datetime import datetime


def local_ip() -> str | None:
    """Адрес в локальной сети: сначала Wi-Fi, потом кабель."""
    ports = subprocess.run(["networksetup", "-listallhardwareports"],
                           capture_output=True, text=True).stdout

    for line in ports.splitlines():
        if not line.startswith("Device:"):
            continue
        device = line.split(":", 1)[1].strip()
        address = subprocess.run(["ipconfig", "getifaddr", device],
                                 capture_output=True, text=True).stdout.strip()
        if address:
            return address
    return None


def main() -> int:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    address = local_ip()

    if not address:
        print(f"{stamp} сети нет — публиковать acai.local не на что", flush=True)
        # Выходим с ошибкой: launchd подождёт и запустит снова, когда
        # сеть появится.
        return 1

    print(f"{stamp} публикую acai.local → {address}", flush=True)

    # Процесс держится в памяти, пока жив агент: Bonjour объявляет имя,
    # пока кто-то его объявляет.
    os.execv("/usr/bin/dns-sd",
             ["dns-sd", "-P", "ACAI", "_http._tcp", "local", "8443", "acai.local", address])


if __name__ == "__main__":
    sys.exit(main())
