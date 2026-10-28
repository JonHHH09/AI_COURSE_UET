# U1: Grafi ndërqytetas

Grafi përbëhet nga 8 qytete (nyje) dhe 9 rrugë ndërqytetase (degë). Është i padrejtuar, sepse çdo rrugë kalohet në të dy drejtimet, dhe i peshuar, sepse çdo degë ka si peshë distancën në kilometra. Distancat janë të përafërta dhe janë marrë nga planifikuesit publikë të rrugëve (distancë me makinë).

Për ta kaluar grafin në sistemin kompjuterik kemi zgjedhur **listën e fqinjësisë**: çdo qytet lidhet me fqinjët e tij dhe distancën deri tek ata (fjalor qytet → {fqinj: km}). Kjo formë është e përshtatshme sepse grafi është i rrallë, me 9 degë nga 28 çifte të mundshme, ndaj lista ruan vetëm rrugët që ekzistojnë dhe nuk harxhon vend si matrica e fqinjësisë. Ajo lexohet lehtë nga programi, përshkohet shpejt (BFS, DFS, Dijkstra) dhe shtimi i një qyteti të ri kërkon vetëm një hyrje të re. Çdo rrugë ruhet në të dy drejtimet me të njëjtën peshë.

Grafi është i lidhur (nga çdo qytet mund të arrihet në çdo tjetër) dhe ka dy cikle (Tiranë–Lezhë–Durrës dhe Tiranë–Durrës–Fier–Elbasan), prandaj ka rrugë alternative midis disa qyteteve.
