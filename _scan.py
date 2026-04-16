import os, re
emoji_pattern = re.compile(r'[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF\U0001FA00-\U0001FAFF\U00002702-\U000027B0\U0000FE0F]+')
count = 0
for root, dirs, files in os.walk('bot'):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            with open(path, encoding='utf-8', errors='ignore') as fh:
                for i, line in enumerate(fh, 1):
                    if emoji_pattern.search(line):
                        count += 1
                        print(path + ':' + str(i) + ': ' + line.strip()[:120])
print('Total: ' + str(count))
