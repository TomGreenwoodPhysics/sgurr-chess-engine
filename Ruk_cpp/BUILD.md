# Building Ruk C++

From this folder:

```bash
g++ -std=c++20 -O3 -march=native -DNDEBUG -Wall -Wextra main.cpp board.cpp evaluation.cpp search.cpp -o Ruk.exe