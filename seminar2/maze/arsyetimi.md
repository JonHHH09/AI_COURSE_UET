# U2: Labirinti me 25 dhoma

Labirinti modelohet si graf: dhomat janë nyjet (25 gjithsej, të numëruara 1–25) dhe dyert midis dhomave janë degët (31 gjithsej). Grafi është i padrejtuar, sepse një derë hapet në të dy drejtimet, dhe i papeshuar, sepse detyra nuk jep distanca. Dhomat janë vendosur në një rrjetë 5×5 dhe vetëm dhomat ngjitur mund të kenë derë mes tyre.

Për ta kaluar në sistemin AI kemi zgjedhur **listën e fqinjësisë**: çdo dhomë lidhet me listën e dhomave ngjitur nëpërmjet dyerve (fjalor dhomë → [fqinjët]). Kjo formë ruan vetëm dyert që ekzistojnë, lexohet lehtë nga programi dhe është e përshtatshme për kërkim në graf (BFS, DFS) për të gjetur rrugën nga hyrja te dalja. Çdo derë ruhet në të dyja dhomat.

Kufizimet e detyrës janë kontrolluar në kod:
- Ka saktësisht 25 dhoma.
- Çdo dhomë ka minimalisht 2 dhe maksimalisht 4 porta. Në labirint kemi 16 dhoma me 2 porta, 6 me 3 porta dhe 3 me 4 porta. Meqë çdo dhomë ka të paktën 2 porta, labirinti nuk ka dhoma pa rrugëdalje, por ka unaza.
- Ka një hyrje (dhoma 1) dhe një dalje (dhoma 25). Hyrja dhe dalja janë dyer për jashtë dhe ruhen si dhoma të veçanta, jo si degë, ndaj nuk numërohen në 2–4 portat e dhomës.
- Grafi është i lidhur, pra dalja arrihet nga hyrja. Rruga më e shkurtër ka 12 dyer.
