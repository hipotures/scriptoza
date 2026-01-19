# Plan wdrożenia refaktoryzacji rename_video_by_tags.py

Ten dokument opisuje kroki niezbędne do ukończenia refaktoryzacji skryptu `video/rename_video_by_tags.py`, tak aby w pełni obsługiwał konfigurację opartą na pliku YAML i umożliwiał stosowanie wielu zestawów reguł (presetów).

## Cel
Naprawa obecnego (niekompletnego) stanu skryptu, który wywołuje nieistniejące funkcje, oraz przeniesienie całej logiki decyzyjnej do zewnętrznej konfiguracji `video/rename_video.yaml`.

## Etapy wdrożenia

### 1. Dokończenie struktury kodu (Zadania programistyczne)
Wymagane jest zaimplementowanie brakujących komponentów, które są już wywoływane w funkcji `main()`:

*   **`load_all_presets()`**:
    *   Lokalizacja pliku: najpierw `./rename_video.yaml`, następnie `~/.config/scriptoza/rename_video.yaml`.
    *   Walidacja schematu YAML (czy posiada klucz `presets`).
    *   Zwracanie słownika presetów oraz ewentualnego komunikatu o błędzie.
*   **`evaluate_tags_for_preset(meta, name, rules)`**:
    *   Przeniesienie logiki z `evaluate_tags` do nowej funkcji obsługującej strukturę z YAML.
    *   Obsługa sekcji `require` (klucze i wartości - AND).
    *   Obsługa sekcji `exclude` (klucze i wartości - OR).
*   **`build_epilog(all_presets)`**:
    *   Aktualizacja istniejącej funkcji `build_epilog`, aby przyjmowała listę presetów.
    *   Dynamiczne generowanie sekcji "Dostępne presety" w pomocy `--help`.

### 2. Migracja konfiguracji
*   Przeniesienie obecnych reguł (np. `AndroidVersion` dla `qvr`) do pliku `video/rename_video.yaml`.
*   Usunięcie z kodu źródłowego stałych: `POSITIVE_KEYS_REQUIRED`, `POSITIVE_VALUE_RULES`, `NEGATIVE_KEYS_PRESENT`, `NEGATIVE_VALUE_RULES`.

### 3. Weryfikacja i Testy
Z uwagi na to, że skrypt operuje na plikach, należy przeprowadzić testy w bezpiecznym środowisku:
1.  **Dry-run test**: Uruchomienie `python3 rename_video_by_tags.py --dry-run --debug` na katalogu z testowymi plikami MP4.
2.  **Walidacja reguł**: Sprawdzenie czy pliki bez tagu `AndroidVersion` są poprawnie pomijane przez preset `qvr`.
3.  **Test kolizji**: Upewnienie się, że `safe_rename_no_overwrite` nadal działa poprawnie przy zmianie nazwy na taką, która już istnieje.

### 4. Sprzątanie
*   Usunięcie nieużywanych importów (jeśli zostaną po refaktoryzacji).
*   Aktualizacja `video/README.md` o informację o nowym sposobie konfiguracji.

## Harmonogram prac
1.  Implementacja funkcji ładującej YAML.
2.  Implementacja nowej logiki ewaluacji reguł.
3.  Naprawa `build_epilog`.
4.  Testy manualne na plikach testowych.
5.  Finalne usunięcie starego kodu (hardcoded rules).