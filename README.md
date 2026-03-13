# Whatsapp-Chatbot

python3 -m venv .chat-bot-env
source .chat-bot-env/bin/activate

pip install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/

pip freeze | grep emergentintegrations >> requirements.txt