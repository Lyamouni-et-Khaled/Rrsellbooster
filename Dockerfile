# Utiliser une image Python officielle et légère
FROM python:3.10-slim

# Définir le répertoire de travail
WORKDIR /usr/src/app

# Copier le fichier des dépendances
COPY requirements.txt ./

# Installer les dépendances système et Python
RUN apt-get update && apt-get install -y libopenjp2-7 && \
    pip install --no-cache-dir -r requirements.txt

# Copier tout le reste de votre projet
COPY . .

# La commande pour lancer votre bot
CMD [ "python", "main.py" ]
