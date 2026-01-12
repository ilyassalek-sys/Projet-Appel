import os
from fastapi import FastAPI, HTTPException, Request
from supabase import create_client, Client
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# Configuration Supabase (Utilise la SERVICE_ROLE_KEY pour le backend car il doit tout voir)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") 
db: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

# --- MODÈLES DE DONNÉES ---
class ToolCall(BaseModel):
    # Structure simplifiée pour l'exemple
    function: dict

# --- ROUTE 1 : INITIALISATION DE L'APPEL ---
@app.post("/call/init")
async def init_call(request: Request):
    payload = await request.json()
    
    # Vapi envoie les détails de l'appel. On récupère le numéro appelé (Celui du Resto)
    # Note: La structure du payload Vapi peut varier, il faut vérifier la doc 'Assistant Request'
    try:
        # Si Vapi appelle via SIP ou Twilio directement
        called_number = payload.get('message', {}).get('phone_number', {}).get('number')
        if not called_number:
             # Fallback pour tests
             called_number = payload.get('phone_number') 
    except:
        raise HTTPException(status_code=400, detail="Numéro introuvable")

    # 1. Identifier le restaurant
    response = db.table('restaurants').select("*").eq('twilio_phone_number', called_number).execute()
    if not response.data:
        # Fallback si le numéro n'est pas reconnu (évite que l'IA plante)
        return {
            "role": "system",
            "content": "Tu es un assistant, mais je ne trouve pas le restaurant associé à ce numéro."
        }
    
    resto = response.data[0]

    # 2. Récupérer le menu ACTIF (Le Kill Switch est ici)
    menu_resp = db.table('menu_items').select("*").eq('restaurant_id', resto['id']).eq('is_available', True).execute()
    menu_text = "\n".join([f"- {m['name']} ({m['price']}€)" for m in menu_resp.data])

    # 3. Construire le Prompt Système
    system_instruction = f"""
    Tu es l'assistant vocal du restaurant {resto['name']}.
    Ton rôle est de prendre des réservations et répondre aux questions sur le menu.
    
    MENU ACTUEL DU JOUR :
    {menu_text}
    IMPORTANT : Si un client demande un plat qui n'est pas dans cette liste ci-dessus, dis poliment qu'il est en rupture de stock aujourd'hui.
    
    Règles de conversation :
    - Sois chaleureux, bref et professionnel.
    - Demande toujours : Nom, Nombre de personnes, Date et Heure.
    - Une fois les infos obtenues, utilise l'outil 'book_table' pour enregistrer.
    """

    # On retourne la configuration à Vapi
    return {
        "assistant": {
            "model": {
                "provider": "openai",
                "model": "gpt-4o",
                "systemPrompt": system_instruction,
                # On définit l'outil ici pour que Vapi sache qu'il existe
                "functions": [
                    {
                        "name": "book_table",
                        "description": "Enregistrer une réservation quand toutes les infos sont là.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "customer_name": {"type": "string"},
                                "party_size": {"type": "integer"},
                                "reservation_datetime": {"type": "string", "description": "Format ISO ou explicite ex: 12 Janvier 20h00"}
                            },
                            "required": ["customer_name", "party_size", "reservation_datetime"]
                        }
                    }
                ]
            }
        }
    }

# --- ROUTE 2 : L'OUTIL DE RÉSERVATION ---
@app.post("/tools/book_table")
async def book_table(request: Request):
    payload = await request.json()
    
    # Extraction des arguments envoyés par GPT-4o
    args = payload.get('message', {}).get('functionCall', {}).get('parameters', {})
    
    # Pour simplifier, on doit retrouver l'ID du resto. 
    # Vapi envoie le contexte de l'appel, on réutilise le numéro appelé ou on passe l'ID dans le contexte.
    # Ici, supposons qu'on refasse la recherche par numéro appelé présent dans le payload global.
    call_data = payload.get('message', {}).get('call', {})
    called_number = call_data.get('phone_number', {}).get('number') # À adapter selon payload réel Vapi
    
    # Recherche ID Resto (Optimisation possible: cacher l'ID dans les metadata de l'appel)
    resto_resp = db.table('restaurants').select("id").eq('twilio_phone_number', called_number).execute()
    if not resto_resp.data:
        return {"result": "Erreur technique: Restaurant introuvable."}
    
    restaurant_id = resto_resp.data[0]['id']

    # Insertion en BDD Supabase
    try:
        db.table('reservations').insert({
            "restaurant_id": restaurant_id,
            "customer_name": args.get('customer_name'),
            "party_size": args.get('party_size'),
            "reservation_time": args.get('reservation_datetime'), # Note: GPT envoie des strings, il faudra peut-être parser en datetime
            "customer_phone": call_data.get('customer', {}).get('number'), # Le numéro de l'appelant
            "status": "confirmed"
        }).execute()
        
        # Ici : Ajouter appel API Firebase/OneSignal pour la notif push
        
        return {"result": "La réservation est confirmée et enregistrée."}
    except Exception as e:
        return {"result": f"Erreur lors de l'enregistrement: {str(e)}"}