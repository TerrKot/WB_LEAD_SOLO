#!/bin/bash
# Простая команда для подсчета количества расчетов и пользователей

echo "🔍 Проверка таблиц в БД:"
docker exec wb_lead_postgres psql -U app -d app -c "\dt"

echo ""
echo "📊 Уникальных пользователей (из таблицы users):"
docker exec wb_lead_postgres psql -U app -d app -t -c "SELECT COUNT(*) FROM users;"

echo "📊 Уникальных пользователей (из таблицы calculations):"
docker exec wb_lead_postgres psql -U app -d app -t -c "SELECT COUNT(DISTINCT user_id) FROM calculations;"

echo "📊 Всего расчетов:"
docker exec wb_lead_postgres psql -U app -d app -t -c "SELECT COUNT(*) FROM calculations;"

