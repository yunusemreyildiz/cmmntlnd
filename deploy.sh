#!/bin/bash

# Şirket sunucusunda çalıştırılacak deployment script

echo "🚀 CmmntLnd Deployment Başlatılıyor..."

# Proje dizinine git
cd /opt/cmmntlnd

# Git'ten en son kodu çek
git pull origin main

# Docker container'ları yeniden başlat
docker-compose down
docker-compose pull
docker-compose up -d

echo "✅ Deployment tamamlandı!"
echo "🌐 Web UI: http://sunucu-ip:5001"
