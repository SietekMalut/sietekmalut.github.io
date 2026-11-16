import sys, re
sys.path.insert(0, '.')
import net
r = net.fetch("https://malutpost.id/")
t = r.text
i = t.find("Misteri Hiu Paus")
print(t[max(0,i-1500):i+400])
print("\n\n=== article tag count:", t.count("<article"))
print("=== h2 count:", t.count("<h2"), " h3:", t.count("<h3"))
