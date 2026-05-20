import re

def parse_cooldown_to_seconds(cooldown_str: str) -> int:
    """Переводит строки вида '1ч. 37м', '13м', '3м. 15с' в секунды"""
    hours = re.search(r'(\d+)\s*ч', cooldown_str)
    minutes = re.search(r'(\d+)\s*м', cooldown_str)
    seconds = re.search(r'(\d+)\s*с', cooldown_str)
    
    total_seconds = 0
    if hours:
        total_seconds += int(hours.group(1)) * 3600
    if minutes:
        total_seconds += int(minutes.group(1)) * 60
    if seconds:
        total_seconds += int(seconds.group(1))
        
    return total_seconds if total_seconds > 0 else 300 # дефолт 5 минут, если не распарсилось

def parse_celestiana_message(text: str):
    """
    Парсит сообщение Celestiana. 
    Возвращает список доступных команд (где открыт замок или стоит галочка)
    и словарь {название_команды: кулдаун_в_секундах}
    """
    commands = []
    cooldowns = {}
    
    # Регулярка ищет строки вида: [5] 🔒 • «Квантовое слияние» | 🔥+400|13м или с ✅
    # Учитываем, что Celestiana переносит строки, склеиваем очищенный текст
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    current_cmd = None
    
    for line in lines:
        # Пытаемся найти начало команды
        match = re.search(r'\[(\d+)\]\s*([✅🔒🔑])\s*•\s*«(.*?)»', line)
        if match:
            status = match.group(2)
            cmd_name = match.group(3)
            current_cmd = cmd_name
            
            # Если команда не заблокирована наглухо (доступна для выбора)
            if status in ['✅', '🔑'] or "🔒" in line: 
                # Позволяем выбирать даже закрытые, если юзер хочет, 
                # но для авто-фарма берем только доступные (например, ✅)
                commands.append(cmd_name)
        
        # Если строка содержит КД и относится к текущей команде
        if current_cmd and '|' in line:
            parts = line.split('|')
            if len(parts) >= 2:
                cd_part = parts[-1].strip() # Последняя часть после |
                cooldowns[current_cmd] = parse_cooldown_to_seconds(cd_part)
                
    return commands, cooldowns
