from pathlib import Path

p = Path(r"C:\Users\Aseman\OneDrive\Desktop\py-code\vinor\app\static\admin\ops-chat.js")
s = p.read_text(encoding="utf-8")
old_rm = "document.removeEventListener('keydown', onKeydown);"
new_rm = "document.removeEventListener('keydown', onKeydown, true);"
old_add = "document.addEventListener('keydown', onKeydown);"
new_add = "document.addEventListener('keydown', onKeydown, true);"
assert old_rm in s, "remove listener not found"
assert old_add in s, "add listener not found"
s = s.replace(old_rm, new_rm, 1).replace(old_add, new_add, 1)
p.write_text(s, encoding="utf-8")
print("ok")
