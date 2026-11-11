# Tutorial: detecção de fraudes com Kafka, Azure e Blob Storage

Este tutorial transforma o exemplo da aula em um pipeline de detecção de
fraudes financeiras:

```text
CSV do Kaggle
    ↓
produtor.py
    ↓ Kafka
Azure Event Hubs
    ↓
consumidor.py
    ↓ HTTP
API FastAPI + modelo scikit-learn
    ↓
Azure Blob Storage
```

O Event Hubs será usado pelo endpoint compatível com Kafka. Não é necessário
criar ou administrar um cluster Kafka separado.

## 1. Pré-requisitos

Você precisará de:

- uma assinatura Azure;
- Azure CLI no Cloud Shell ou no computador;
- Python 3.11 ou superior;
- Docker, ou GitHub Container Registry para publicar a imagem;
- o CSV do dataset [Financial Fraud Detection Dataset](https://www.kaggle.com/datasets/sriharshaeedala/financial-fraud-detection-dataset).

No Azure Portal, abra o **Cloud Shell** e selecione **PowerShell**. Depois:

```powershell
cd C:\Users\tione\Desktop\Kafka\infra-para-ia\aula5-dados
```

No Cloud Shell, o caminho local pode ser diferente. Nesse caso, clone o
repositório e entre na pasta correspondente.

Instale as dependências:

```powershell
python -m pip install -r requirements.txt
```

## 2. Baixar o dataset diretamente no Azure

Não faça upload do CSV pelo Portal e não copie o dataset para a imagem Docker.
O arquivo do Kaggle tem aproximadamente 180 MB, enquanto a API precisa
somente do `modelo_fraude.pkl` depois do treinamento.

Crie uma conta no Kaggle, gere um token em **Settings → API → Create New
Token** e defina as credenciais apenas na sessão atual do Cloud Shell:

```powershell
$env:KAGGLE_USERNAME = "seu_usuario_kaggle"
$env:KAGGLE_KEY = "sua_chave_kaggle"
```

Baixe o ZIP diretamente pelo endpoint da API do Kaggle:

```powershell
curl.exe -L `
  -u "${env:KAGGLE_USERNAME}:${env:KAGGLE_KEY}" `
  -o fraud-dataset.zip `
  https://www.kaggle.com/api/v1/datasets/download/sriharshaeedala/financial-fraud-detection-dataset
```

Extraia e localize o CSV:

```powershell
Expand-Archive `
  -Path fraud-dataset.zip `
  -DestinationPath kaggle-fraud `
  -Force

Get-ChildItem kaggle-fraud -Filter *.csv
```

O nome do CSV pode variar conforme a versão do dataset. Copie o CSV encontrado
para o nome esperado pelo projeto:

```powershell
$csv = Get-ChildItem kaggle-fraud -Filter *.csv | Select-Object -First 1
Copy-Item $csv.FullName fraud.csv
```

Se aparecer `401 Unauthorized`, a sessão não está autenticada no Kaggle.
Gere um token novo e repita a definição das variáveis. Não salve
`KAGGLE_KEY` em `config.env`, no Git ou na imagem Docker.

Se o objetivo for apenas armazenar o arquivo no Blob, sem treiná-lo nessa
máquina, execute os comandos abaixo depois da seção **5.1 Criar o Blob
Storage**, quando `$STORAGE_CONNECTION` já tiver sido definida. O download do
Kaggle é um ZIP; o Blob recebe apenas o CSV extraído:

```powershell
az storage container create `
  --name dataset `
  --connection-string $STORAGE_CONNECTION `
  --public-access off

az storage blob upload `
  --container-name dataset `
  --name fraud.csv `
  --file fraud.csv `
  --connection-string $STORAGE_CONNECTION `
  --overwrite
```

O treinamento deste tutorial continua sendo executado localmente ou no Cloud
Shell. O ACI é usado para servir inferência e não para treinar o modelo.

## 3. Treinar o modelo

Se você já possui o arquivo, salve-o como `fraud.csv` dentro desta pasta.

O treinamento usa as colunas:

```text
step,type,amount,isFlaggedFraud
```

e usa `isFraud` como alvo. As colunas de saldo não são usadas porque o próprio
dataset alerta sobre possível vazamento de informação. `nameOrig` e `nameDest`
também ficam fora para evitar overfitting em identificadores.

Treine o modelo:

```powershell
python treinar_fraude.py --arquivo fraud.csv
```

O comando deve criar:

```text
modelo_fraude.pkl
```

O resultado do treinamento exibe `precision`, `recall`, `f1-score` e `ROC-AUC`.
Não use somente acurácia, pois a quantidade de transações fraudulentas é
muito menor que a quantidade de transações normais.

## 4. Testar a API localmente

Inicie a API:

```powershell
python -m uvicorn api:app --host 0.0.0.0 --port 8000
```

Em outro terminal, verifique a saúde:

```powershell
curl.exe http://localhost:8000/health
```

Teste uma transação:

```powershell
curl.exe -X POST http://localhost:8000/prediz `
  -H "Content-Type: application/json" `
  -d '{\"step\":1,\"type\":\"TRANSFER\",\"amount\":250000,\"isFlaggedFraud\":0}'
```

A resposta esperada possui este formato:

```json
{
  "fraude": true,
  "probabilidade_fraude": 0.9731
}
```

Pare a API com `Ctrl+C` antes de continuar.

## 5. Criar os recursos Azure

Defina nomes únicos para os recursos:

```powershell
$GRUPO="fraude-rg"
$REGIAO="brazilsouth"
$SUFIXO="seunome123"
$STORAGE="stfraude$SUFIXO"
$EVENTHUB_NS="ehfraude$SUFIXO"
$EVENTHUB="fraudes"
```

Crie o resource group:

```powershell
az group create `
  --name $GRUPO `
  --location $REGIAO
```

Registre os provedores necessários:

```powershell
az provider register --namespace Microsoft.Storage
az provider register --namespace Microsoft.EventHub
az provider register --namespace Microsoft.ContainerInstance
```

### 4.1 Criar o Blob Storage

Crie a Storage Account:

```powershell
az storage account create `
  --name $STORAGE `
  --resource-group $GRUPO `
  --location $REGIAO `
  --sku Standard_LRS `
  --kind StorageV2 `
  --allow-blob-public-access false
```

Obtenha a connection string:

```powershell
$STORAGE_CONNECTION = az storage account show-connection-string `
  --name $STORAGE `
  --resource-group $GRUPO `
  --query connectionString `
  --output tsv
```

Crie o container privado onde os resultados serão gravados:

```powershell
az storage container create `
  --name avaliacoes `
  --connection-string $STORAGE_CONNECTION `
  --public-access off
```

O código atual usa o container `avaliacoes` para manter compatibilidade com o
exemplo da aula. Cada resultado será salvo como:

```text
resultados/particao-offset.json
```

Esse nome torna o processamento idempotente: se uma mensagem for reprocessada,
o mesmo Blob é sobrescrito.

### 4.2 Criar o Event Hubs compatível com Kafka

Crie um namespace **Standard**. O tier Basic não fornece o endpoint Kafka:

```powershell
az eventhubs namespace create `
  --name $EVENTHUB_NS `
  --resource-group $GRUPO `
  --location $REGIAO `
  --sku Standard `
  --capacity 1
```

Crie o Event Hub:

```powershell
az eventhubs eventhub create `
  --name $EVENTHUB `
  --namespace-name $EVENTHUB_NS `
  --resource-group $GRUPO `
  --partition-count 4 `
  --message-retention 1
```

Obtenha a connection string do namespace:

```powershell
$EVENTHUB_CONNECTION = az eventhubs namespace authorization-rule keys list `
  --resource-group $GRUPO `
  --namespace-name $EVENTHUB_NS `
  --name RootManageSharedAccessKey `
  --query primaryConnectionString `
  --output tsv
```

Para produção, crie políticas separadas com permissões somente de envio e
leitura. `RootManageSharedAccessKey` é usado aqui apenas para simplificar a
prática.

## 6. Publicar a API no Azure Container Instances

O `Dockerfile` desta pasta copia `api.py` e `modelo_fraude.pkl` para a imagem.
Construa a imagem localmente:

```powershell
docker build -t fraude-api:1.0 .
```

Para publicar sem configurar um registro privado, use o GitHub Container
Registry. Crie um token do GitHub com permissão `write:packages` e faça login:

```powershell
docker tag fraude-api:1.0 ghcr.io/SEU_USUARIO/fraude-api:1.0
docker login ghcr.io
docker push ghcr.io/SEU_USUARIO/fraude-api:1.0
```

Deixe o pacote público no GitHub ou configure credenciais de pull no ACI.
Depois crie o container no Azure:

```powershell
az container create `
  --resource-group $GRUPO `
  --name fraude-api `
  --image ghcr.io/SEU_USUARIO/fraude-api:1.0 `
  --registry-login-server ghcr.io `
  --ip-address Public `
  --ports 8000 `
  --cpu 1 `
  --memory 2
```

Se o pacote for público, o ACI pode ser criado sem usuário e senha do
registro. Para um pacote privado, acrescente:

```powershell
  --registry-username SEU_USUARIO `
  --registry-password SEU_TOKEN
```

Descubra o IP público:

```powershell
$API_IP = az container show `
  --resource-group $GRUPO `
  --name fraude-api `
  --query ipAddress.ip `
  --output tsv

$API_URL = "http://$API_IP`:8000"
```

Valide a API:

```powershell
curl.exe "$API_URL/health"
```

Espere o container terminar de iniciar se a resposta ainda não estiver
disponível.

## 7. Configurar produtor e consumidor

Copie o arquivo de configuração:

```powershell
Copy-Item config.env.exemplo config.env
```

Edite `config.env` e preencha:

```text
EVENTHUB_NAMESPACE=ehfraudeseunome123
EVENTHUB_CONNECTION=Endpoint=sb://...
STORAGE_CONNECTION=DefaultEndpointsProtocol=https;...
API_URL=http://IP_DA_API:8000
```

Não coloque aspas e não publique esse arquivo. Ele já está protegido pelo
`.gitignore`.

## 8. Executar o pipeline

Abra dois terminais na pasta `aula5-dados`.

No primeiro, publique algumas transações:

```powershell
python produtor.py --arquivo fraud.csv --quantidade 100
```

O produtor publica no Event Hub `fraudes`. A chave `nameOrig` é usada como
chave Kafka para manter transações da mesma conta na mesma partição.

No segundo, inicie o consumidor:

```powershell
python consumidor.py `
  --grupo fraude-api `
  --api `
  --blob `
  --desde-o-inicio
```

O consumidor:

1. lê a mensagem do Event Hubs;
2. envia os atributos para `POST /prediz`;
3. recebe a classificação;
4. grava o JSON no Blob Storage;
5. confirma o offset somente depois da gravação.

Consulte os resultados:

```powershell
az storage blob list `
  --container-name avaliacoes `
  --connection-string $STORAGE_CONNECTION `
  --output table
```

Baixe um resultado específico:

```powershell
az storage blob download `
  --container-name avaliacoes `
  --name resultados/0-0.json `
  --file resultado.json `
  --connection-string $STORAGE_CONNECTION
```

O JSON terá uma estrutura semelhante a:

```json
{
  "id": "C123",
  "transacao": {
    "step": 1,
    "type": "TRANSFER",
    "amount": 250000.0,
    "isFlaggedFraud": 0
  },
  "fraude": true,
  "probabilidade_fraude": 0.9731,
  "particao": 0,
  "offset": 0
}
```

## 9. Reprocessar o histórico

Use outro consumer group para reprocessar as mensagens sem interferir no grupo
principal:

```powershell
python consumidor.py `
  --grupo fraude-reprocessamento `
  --api `
  --blob `
  --desde-o-inicio `
  --prefixo reprocessados
```

Os novos resultados aparecerão em `reprocessados/`.

## 10. Limpar os recursos para evitar custos

Quando terminar a prática, apague o resource group inteiro:

```powershell
az group delete `
  --name $GRUPO `
  --yes `
  --no-wait
```

Isso remove o Event Hubs, o Storage Account e o Container Instance criados
neste tutorial.

## Problemas comuns

| Problema | Correção |
|---|---|
| O Event Hubs recusa a conexão Kafka | Use namespace `Standard`, não `Basic`. |
| `API_URL` não responde | Verifique o IP do ACI e aguarde o container iniciar. |
| Blob não aparece | Confirme `--api --blob` e a connection string da Storage Account. |
| O consumidor não recebe mensagens | Use um grupo novo com `--desde-o-inicio`. |
| Modelo não encontrado no Docker | Execute `python treinar_fraude.py --arquivo fraud.csv` antes do `docker build`. |
| Acurácia muito alta ou suspeita | Verifique vazamento de dados e mantenha as colunas de saldo fora do treinamento. |
