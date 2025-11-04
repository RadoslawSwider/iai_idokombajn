
import pandas as pd
from bs4 import BeautifulSoup
import openai
import json
import time
import os

def clean_html(html_text):
    if not isinstance(html_text, str): return ""
    soup = BeautifulSoup(html_text, 'html.parser')
    return soup.get_text(separator=' ', strip=True)

def extract_features_with_ai(client, text_description, progress_callback, should_stop_callback):
    while True:
        try:
            if not text_description or len(text_description) < 20:
                progress_callback("Pomijam: Opis jest zbyt krótki lub pusty.")
                return []
            
            prompt = f"Przeanalizuj poniższy opis produktu. Wyodrębnij od 3 do 5 jego najważniejszych, konkretnych cech (materiał, funkcje, wymiary itp.). Zwróć je jako zwięzłą listę. Opis: --- {text_description} ---"
            
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Jesteś precyzyjnym analitykiem danych produktowych."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0
            )
            content = response.choices[0].message.content
            features = [line.strip().lstrip('0123456789. -*') for line in content.split('\n') if line.strip()]
            progress_callback(f"Wyodrębniono cechy: {features}")
            return features
        except Exception as e:
            progress_callback(f"Błąd podczas ekstrakcji cech: {e}. Próbuję ponownie za 15 sekund...")
            time.sleep(15)
            if should_stop_callback():
                return []

def generate_creative_content_with_ai(client, feature_list, user_prompt, progress_callback, should_stop_callback):
    while True:
        try:
            if not feature_list:
                progress_callback("Pomijam: Brak cech do wygenerowania treści.")
                return None
            
            features_str = ", ".join(feature_list)
            prompt = user_prompt.replace('{features_str}', features_str)
            
            response = client.chat.completions.create(
                model="gpt-4o",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "Jesteś kreatywnym copywriterem i zwracasz odpowiedzi w formacie JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7
            )
            content = response.choices[0].message.content
            progress_callback("Treść kreatywna została wygenerowana.")
            return json.loads(content)
        except Exception as e:
            progress_callback(f"Błąd podczas generowania treści kreatywnej: {e}. Próbuję ponownie za 15 sekund...")
            time.sleep(15)
            if should_stop_callback():
                return None

def create_product_html(product_name, teaser, main_description, feature_list, color):
    # More robust CSS with the selected color
    style = f"""
    .product-container{{
        font-family: Arial, sans-serif;
        background-color: #0d0804; /* Dark background for contrast */
        color: #f0f0f0;
        padding: 25px;
        max-width: 800px;
        margin: 20px auto;
        border-radius: 8px;
        box-shadow: 0 4px 15px rgba(0,0,0,.5);
        border: 2px solid {color};
    }}
    .product-title{{
        color: {color} !important;
        font-size: 28px;
        margin-top: 0;
        margin-bottom: 10px;
    }}
    .product-price{{ /* Using this for the teaser */
        font-size: 18px;
        font-style: italic;
        color: #ccc;
        margin-bottom: 20px;
    }}
    .product-description{{
        font-size: 16px;
        line-height: 1.6;
        margin-bottom: 20px;
    }}
    .product-features{{
        list-style: none;
        padding-left: 0;
        margin-bottom: 25px;
    }}
    .product-features li{{
        padding-left: 20px;
        position: relative;
        margin-bottom: 8px;
        font-size: 15px;
    }}
    .product-features li::before{{
        content: '✔';
        color: {color};
        position: absolute;
        left: 0;
        font-weight: 700;
    }}
    """
    list_items_html = "".join([f"<li>{feature}</li>" for feature in feature_list])
    final_html = f'<style>{style.replace("\n", "").strip()}</style>' \
                 f'<div class="product-container">' \
                 f'<h1 class="product-title">{product_name}</h1>' \
                 f'<p class="product-price">{teaser}</p>' \
                 f'<p class="product-description">{main_description}</p>' \
                 f'<ul class="product-features">{list_items_html}</ul>' \
                 f'</div>'
    return final_html

def run_description_generator(api_key, input_path, user_prompt, use_html_frame, frame_color, id_column, description_column, progress_callback, should_stop_callback):
    progress_callback("--- Rozpoczynam tworzenie nowych opisów produktów (Silnik: OpenAI) ---")
    
    try:
        client = openai.OpenAI(api_key=api_key)
        progress_callback("Pomyślnie połączono z API OpenAI.")
    except Exception as e:
        progress_callback(f"BŁĄD KRYTYCZNY: Nie udało się połączyć z API OpenAI. Sprawdź klucz. Błąd: {e}")
        return None

    try:
        df_full = pd.read_csv(input_path)
        progress_callback(f"Znaleziono plik '{os.path.basename(input_path)}' i wczytano {len(df_full)} produktów.")
    except FileNotFoundError:
        progress_callback(f"BŁĄD KRYTYCZNY: Nie znaleziono pliku '{input_path}'.")
        return None
    except Exception as e:
        progress_callback(f"BŁĄD KRYTYCZNY: Nie można wczytać pliku CSV: {e}")
        return None

    base, ext = os.path.splitext(input_path)
    output_path = f"{base}_wygenerowane{ext}"

    processed_ids = set()
    if os.path.exists(output_path):
        progress_callback("Znaleziono istniejący plik wyjściowy. Wznawiam pracę...")
        try:
            df_processed = pd.read_csv(output_path)
            if not df_processed.empty and id_column in df_processed.columns:
                processed_ids = set(df_processed[id_column].dropna().tolist())
            progress_callback(f"Znaleziono {len(processed_ids)} już przetworzonych produktów.")
        except (pd.errors.EmptyDataError, KeyError):
            progress_callback("Plik wyjściowy jest pusty lub uszkodzony. Zaczynam od początku.")
            if os.path.exists(output_path): os.remove(output_path)

    df_todo = df_full[~df_full[id_column].isin(processed_ids)].copy()
    
    if df_todo.empty:
        progress_callback("Wszystkie produkty zostały już przetworzone. Kończę pracę.")
        return output_path
        
    progress_callback(f"Pozostało do przetworzenia: {len(df_todo)} produktów.")
    
    total_rows = len(df_todo)
    for i, (index, row) in enumerate(df_todo.iterrows()):
        if should_stop_callback():
            progress_callback("Przerwano przez użytkownika.")
            break

        progress_callback(f"({i+1}/{total_rows}) Przetwarzam produkt ID: {row.get(id_column)}")
        
        clean_text = clean_html(row.get(description_column, ''))
        
        row_prefix = f"({i+1}/{total_rows})"
        def prefixed_callback(msg):
            progress_callback(f"{row_prefix} {msg}")

        features = extract_features_with_ai(client, clean_text, prefixed_callback, should_stop_callback)
        if not features:
            # Check if we should stop after the feature extraction failed but before continuing
            if should_stop_callback():
                progress_callback("Przerwano przez użytkownika.")
                break
            progress_callback(f"({i+1}/{total_rows}) Pomijam produkt z powodu braku cech.")
            continue

        creative_content = generate_creative_content_with_ai(client, features, user_prompt, prefixed_callback, should_stop_callback)

        result_row = { id_column: row.get(id_column) }
        
        if creative_content and isinstance(creative_content, dict):
            product_name = creative_content.get('nazwa_produktu', 'Nowy Produkt')
            
            if use_html_frame:
                final_description = create_product_html(
                    product_name, 
                    creative_content.get('zajawka', ''), 
                    creative_content.get('opis_glowny', ''), 
                    creative_content.get('cechy_marketingowe', []),
                    frame_color
                )
            else:
                zajawka = creative_content.get('zajawka', '')
                opis_glowny = creative_content.get('opis_glowny', '')
                cechy = "\n".join([f"- {feat}" for feat in creative_content.get('cechy_marketingowe', [])])
                final_description = f"{product_name}\n\n{zajawka}\n\n{opis_glowny}\n\nCechy:\n{cechy}"

            result_row['wygenerowana_nazwa'] = product_name
            result_row['nowy_opis_html'] = final_description
            progress_callback(f"({i+1}/{total_rows}) Sukces: Wygenerowano opis dla produktu ID: {row.get(id_column)}")
        else:
            result_row['wygenerowana_nazwa'] = "BŁĄD"
            result_row['nowy_opis_html'] = "BŁĄD"
            progress_callback(f"({i+1}/{total_rows}) BŁĄD: Nie udało się wygenerować treści dla produktu ID: {row.get(id_column)}")

        df_to_save = pd.DataFrame([result_row])
        df_to_save.to_csv(output_path, mode='a', header=not os.path.exists(output_path), index=False, encoding='utf-8')
        
        time.sleep(1)

    progress_callback(f"\n--- Zakończono! ---")
    progress_callback(f"Wszystkie produkty zostały przetworzone.")
    progress_callback(f"Wyniki znajdują się w pliku: {output_path}")
    return output_path
