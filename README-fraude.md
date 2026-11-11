# Tutorial: detecção de fraudes com Azure Event Hubs

Este tutorial cria o pipeline completo da aplicação:

```text
Dataset do Kaggle
        |
        v
  produtor.py
        |
        v
Azure Event Hubs (Kafka)
        |
        v
  consumidor.py -----> API FastAPI -----> Azure Blob Storage
```

O Event Hubs fornece o endpoint compatível com Kafka. Não é necessário criar
ou administrar um cluster Kafka separado.

## 1. Visão geral do que será criado

Ao final, você terá:

1. um Resource Group para reunir os recursos da prática;
2. uma Storage Account com o container privado `avaliacoes`;
3. um namespace do Event Hubs no tier **Standard**;
4. um Event Hub chamado `fraudes`, com quatro partições;
5. uma API FastAPI publicada no Azure Container Instances (ACI);
6. um produtor que envia transações pelo protocolo Kafka;
7. um consumidor que chama a API e grava as classificações no Blob Storage.

O fluxo usa:

- `fraud.csv`: dataset local, baixado automaticamente pelo treinamento;
- `modelo_fraude.pkl`: modelo treinado e incluído na imagem da API;
- `config.env`: credenciais e endereços usados pelo produtor e consumidor.

## 2. Pré-requisitos

Você precisará de:

- uma conta com uma assinatura Azure;
- acesso ao [Portal Azure](https://portal.azure.com/);
- uma conta no GitHub;
- Docker instalado localmente, ou acesso ao GitHub Codespaces;
- Python 3.11 ou superior;
- um token do GitHub com permissão para publicar pacotes no GHCR.

O dataset não deve ser enviado ao GitHub. O arquivo tem centenas de megabytes
e já está listado no [`.gitignore`](.gitignore).

## 3. Abrir o Azure Cloud Shell

1. Acesse o [Portal Azure](https://portal.azure.com/) e faça login.
2. Clique no ícone **Cloud Shell** na barra superior.
3. Selecione **Bash** como shell.
4. Na primeira abertura, escolha uma assinatura e confirme a criação do
   armazenamento solicitado pelo Cloud Shell.

Clone o repositório e entre na pasta do projeto:

```bash
git clone https://github.com/tioneOliveira/Kafka-detectar-fraude.git
cd Kafka-detectar-fraude
```

Instale as dependências:

```bash
python3 -m pip install --user -r requirements.txt
```

Se o Cloud Shell não permitir a instalação no ambiente global, crie um
ambiente virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 4. Baixar o dataset e treinar o modelo

Não baixe o dataset manualmente pelo Portal. O script faz o download do ZIP
publicamente e extrai o primeiro CSV encontrado quando `fraud.csv` ainda não
existe.

Execute:

```bash
python treinar_fraude.py
```

O comando:

1. baixa o dataset do Kaggle;
2. extrai `fraud.csv`;
3. treina o classificador;
4. salva `modelo_fraude.pkl`.

O treinamento usa as colunas:

```text
step,type,amount,isFlaggedFraud
```

e usa `isFraud` como alvo. As colunas de saldo não são usadas para evitar
vazamento de informação, e os identificadores de contas não são usados para
evitar overfitting.

Ao terminar, confira os arquivos:

```bash
ls -lh fraud.csv modelo_fraude.pkl
```

O relatório exibido no terminal contém `precision`, `recall`, `f1-score` e
`ROC-AUC`. Como as fraudes são minoria, não avalie o modelo somente pela
acurácia.

## 5. Testar a API localmente

Antes de publicar a API, faça um teste local:

```bash
python -m uvicorn api:app --host 0.0.0.0 --port 8000
```

Abra outra aba do Cloud Shell ou outro terminal e execute:

```bash
curl http://localhost:8000/health
```

Teste uma transação:

```bash
curl -X POST http://localhost:8000/prediz \
  -H 'Content-Type: application/json' \
  -d '{"step":1,"type":"TRANSFER","amount":250000,"isFlaggedFraud":0}'
```

A resposta deve conter `fraude` e `probabilidade_fraude`. Pare o servidor
com `Ctrl+C` antes de continuar.

## 6. Criar o Resource Group pelo Portal

O Resource Group agrupa os recursos e facilita a limpeza no final.

1. No Portal Azure, pesquise **Resource groups**.
2. Clique em **Create**.
3. Selecione a assinatura.
4. Em **Resource group**, informe `fraude-rg` ou outro nome.
5. Em **Region**, escolha a região mais próxima, por exemplo `Brazil
   South`.
6. Clique em **Review + create** e depois em **Create**.

Anote o nome exato do Resource Group e da região escolhida. Eles serão usados
nos próximos passos.

## 7. Criar a Storage Account

### 7.1 Criar a conta

1. Pesquise **Storage accounts** no Portal Azure.
2. Clique em **Create**.
3. Em **Subscription**, selecione sua assinatura.
4. Em **Resource group**, escolha `fraude-rg`.
5. Em **Storage account name**, informe um nome único, somente com letras
   minúsculas e números, por exemplo `stfraude12345`.
6. Escolha a mesma região do Resource Group.
7. Em **Performance**, mantenha **Standard**.
8. Em **Redundancy**, selecione **Locally-redundant storage (LRS)**.
9. Abra **Advanced** e deixe o acesso público a blobs desabilitado.
10. Clique em **Review + create** e depois em **Create**.

### 7.2 Criar o container de resultados

1. Abra a Storage Account criada.
2. No menu esquerdo, acesse **Data storage > Containers**.
3. Clique em **+ Container**.
4. Informe o nome `avaliacoes`.
5. Em **Public access level**, selecione **Private (no anonymous access)**.
6. Clique em **Create**.

O consumidor grava os resultados neste container, usando nomes como:

```text
resultados/fraude/0-0.json
resultados/normal/1-3.json
```

### 7.3 Copiar a connection string

1. Na Storage Account, acesse **Security + networking > Access keys**.
2. Clique em **Show** ao lado de `key1`.
3. Copie o valor completo de **Connection string**.
4. Não publique esse valor no GitHub, em imagens Docker ou em mensagens.

## 8. Criar o Event Hubs pelo Portal

### 8.1 Criar o namespace

1. Pesquise **Event Hubs** no Portal Azure.
2. Clique em **Create**.
3. Em **Subscription**, selecione sua assinatura.
4. Em **Resource group**, escolha `fraude-rg`.
5. Informe um nome único para o namespace, por exemplo `ehfraude12345`.
6. Escolha a mesma região dos recursos anteriores.
7. Em **Pricing tier**, selecione **Standard**.
8. Mantenha as opções de rede padrão para esta prática.
9. Clique em **Review + create** e depois em **Create**.

O tier **Basic** não oferece o endpoint Kafka usado pelo projeto.

### 8.2 Criar o Event Hub

1. Abra o namespace criado.
2. No menu esquerdo, acesse **Entities > Event Hubs**.
3. Clique em **+ Event Hub**.
4. Em **Name**, informe `fraudes`.
5. Em **Partition count**, informe `4`.
6. Em **Message retention**, informe `1` dia.
7. Clique em **Create**.

### 8.3 Copiar a connection string

1. Dentro do namespace, acesse **Settings > Shared access policies**.
2. Abra `RootManageSharedAccessKey`.
3. Copie **Connection string-primary key**.
4. Para produção, crie políticas separadas para envio e leitura. A chave
   `RootManageSharedAccessKey` é usada aqui apenas para simplificar a prática.

## 9. Preparar o arquivo de configuração

Na pasta do projeto, crie uma cópia do exemplo:

```bash
cp config.env.exemplo config.env
```

Edite o arquivo:

```bash
nano config.env
```

Preencha os valores:

```text
EVENTHUB_NAMESPACE=ehfraude12345
EVENTHUB_CONNECTION=Endpoint=sb://...
STORAGE_CONNECTION=DefaultEndpointsProtocol=https;...
API_URL=http://IP_DA_API:8000
```

Use somente o nome do namespace em `EVENTHUB_NAMESPACE`, sem
`.servicebus.windows.net`. Cole as connection strings completas, sem aspas.

O arquivo `config.env` está protegido pelo [`.gitignore`](.gitignore). Nunca
publique as chaves.

Para manter as credenciais somente no computador local, adicione também ao
`config.env` (não use valores reais neste README):

```text
GITHUB_USERNAME=tioneOliveira
GITHUB_TOKEN=COLE_O_TOKEN_LOCALMENTE
```

Esse arquivo contém segredos em texto puro. Use-o somente localmente e nunca
o envie para o GitHub. O token deve ser revogado e recriado se for exposto.

## 10. Publicar a API no GitHub Container Registry

O Dockerfile copia somente `api.py` e `modelo_fraude.pkl`; o `fraud.csv` não
vai para a imagem.

### 10.1 Criar um token do GitHub

No GitHub:

1. Clique na sua foto de perfil e abra **Settings**.
2. Acesse **Developer settings > Personal access tokens**.
3. Crie um token **classic** com as permissões `write:packages` e
   `read:packages`.
4. Se a conta usar uma organização com SSO, autorize o token para essa
   organização.
5. Copie o token somente uma vez e mantenha-o em segurança.

O nome de usuário pode conter letras maiúsculas no login. Porém, o caminho da
imagem no GHCR deve ser minúsculo. Se o `docker push` enviar algumas camadas e
terminar com `denied`, confirme também em **GitHub > Packages** que a conta
possui permissão de escrita no pacote e, caso ele esteja vinculado a um
repositório, que o token possui acesso a esse repositório.

### 10.2 Construir e publicar a imagem

O Azure Cloud Shell não executa um daemon Docker. Portanto, não rode
`docker build` no terminal do Cloud Shell: a mensagem
`Cannot connect to the Docker daemon` indica exatamente essa limitação.

No Windows, abra o **Docker Desktop** pelo menu Iniciar e aguarde até o
status indicar **Engine running**. Se aparecer a opção **Switch to Linux
containers**, selecione-a, pois a imagem usa `python:3.12-slim`.

Confirme que o engine está disponível:

```powershell
docker version
```

O comando deve exibir as seções **Client** e **Server**. Se aparecer
`dockerDesktopLinuxEngine` ou `The system cannot find the file specified`,
aguarde o Docker Desktop iniciar ou reinicie-o antes de continuar.

Depois, clone o repositório e entre na pasta do projeto:

```bash
git clone https://github.com/tioneOliveira/Kafka-detectar-fraude.git
cd Kafka-detectar-fraude
```

O computador local precisa conter o `modelo_fraude.pkl` gerado na etapa 4.
Se ainda não o tiver, execute localmente:

```bash
python treinar_fraude.py
```

Com o Docker Desktop em execução, construa a imagem:

```bash
docker build -t fraude-api:1.0 .
```

No PowerShell, carregue as variáveis do `config.env` somente na sessão atual:

```powershell
Get-Content .\config.env | Where-Object { $_ -match '^\s*[^#].*=' } |
  ForEach-Object {
    $name, $value = $_ -split '=', 2
    [Environment]::SetEnvironmentVariable(
      $name.Trim(),
      $value.Trim(),
      'Process'
    )
  }

$env:GITHUB_TOKEN | docker login ghcr.io `
  -u $env:GITHUB_USERNAME `
  --password-stdin
```

Publique a imagem usando o mesmo nome de usuário:

```powershell
$registryUser = $env:GITHUB_USERNAME.ToLowerInvariant()
docker tag fraude-api:1.0 "ghcr.io/$registryUser/fraude-api:1.0"
docker push "ghcr.io/$registryUser/fraude-api:1.0"
```

O `docker push` precisa terminar exibindo um digest (`sha256:...`). Confirme
que a tag está disponível antes de criar o ACI:

```powershell
docker manifest inspect "ghcr.io/$registryUser/fraude-api:1.0"
```

No GitHub, abra o pacote em **Packages**, configure a visibilidade como
**Public** ou prepare credenciais de pull para o ACI.

## 11. Criar o Azure Container Instance pelo Portal

O ACI executará a API FastAPI.

1. No Portal Azure, pesquise **Container Instances**.
2. Clique em **Create**.
3. Na aba **Basics**, selecione a assinatura e o Resource Group `fraude-rg`.
4. Em **Container name**, informe `fraude-api`.
5. Em **Image source**, selecione **Other registry**.
6. Em **Image**, informe
   `ghcr.io/tioneoliveira/fraude-api:1.0` (o caminho deve ser minúsculo).
7. Se o pacote for privado, informe na seção de registro:
   - **Registry server:** `ghcr.io`
   - **Username:** seu usuário do GitHub
   - **Password:** um token classic com `read:packages`
8. Se o pacote for público, confirme que a tag `1.0` está publicada e
   disponível sem autenticação.
9. Escolha a mesma região dos demais recursos.
10. Na aba **Networking**, selecione **Public**.
11. Informe a porta `8000` como porta TCP.
12. Se desejar, configure um **DNS name label** único para obter um endereço
    estável.
13. Na aba **Advanced**, mantenha a política de reinício como `Always` para
    a API.
14. Em **Review + create**, valide as configurações e clique em **Create**.

Depois que a implantação terminar:

1. Abra o Container Instance.
2. Acesse **Overview**.
3. Copie o **IP address** público.
4. Aguarde o estado ficar **Running**.

Defina a URL da API na sessão do Cloud Shell:

```bash
export API_URL="http://IP_PUBLICO:8000"
curl "$API_URL/health"
```

Se a resposta ainda não aparecer, aguarde alguns minutos e confira
**Container > Logs** no menu do ACI.

Atualize `API_URL` no `config.env` com o mesmo endereço. Se usar um DNS label,
prefira o nome DNS em vez do IP:

```text
API_URL=http://NOME_DNS.REGIAO.azurecontainer.io:8000
```

## 12. Executar o produtor e o consumidor

Abra duas abas do Cloud Shell ou dois terminais na pasta do projeto.

### 12.1 Iniciar o consumidor

Na primeira aba, execute:

```bash
python consumidor.py \
  --grupo fraude-api \
  --api \
  --blob \
  --desde-o-inicio
```

O consumidor:

1. lê mensagens do Event Hub `fraudes`;
2. envia os atributos para `POST /prediz`;
3. recebe a classificação;
4. grava um JSON no container `avaliacoes`;
5. confirma o offset somente depois da gravação.

### 12.2 Publicar transações

Na segunda aba, execute:

```bash
python produtor.py --arquivo fraud.csv --quantidade 100
```

O produtor envia 100 transações, aproximadamente uma por segundo. A chave
`nameOrig` mantém transações da mesma conta na mesma partição.

## 13. Consultar os resultados no Portal

1. No Portal Azure, abra a Storage Account.
2. Acesse **Data storage > Containers > avaliacoes**.
3. Abra a pasta `resultados`.
4. Selecione um arquivo JSON para consultar ou baixar.

Também é possível listar os blobs pelo Cloud Shell:

```bash
az storage blob list \
  --container-name avaliacoes \
  --connection-string "$STORAGE_CONNECTION" \
  --output table
```

Para baixar um resultado:

```bash
az storage blob download \
  --container-name avaliacoes \
  --name resultados/fraude/0-0.json \
  --file resultado.json \
  --connection-string "$STORAGE_CONNECTION"
```

Um resultado terá formato semelhante a:

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

## 14. Reprocessar o histórico

Para reprocessar as mensagens desde o início sem interferir no grupo principal,
use outro nome de grupo:

```bash
python consumidor.py \
  --grupo fraude-reprocessamento \
  --api \
  --blob \
  --desde-o-inicio \
  --prefixo reprocessados
```

Os novos resultados aparecerão em `reprocessados/fraude/` e
`reprocessados/normal/`.

## 15. Retomar a execução após o Cloud Shell expirar

Use este roteiro quando o Resource Group e os recursos Azure já existirem,
mas o terminal temporário tiver sido reiniciado. Ele não recria recursos, não
republica a imagem Docker e não altera o Container Instance.

### 15.1 Reabrir o Cloud Shell e baixar o projeto

Abra o Cloud Shell em **Bash**, clone o projeto e instale as dependências:

```bash
git clone https://github.com/tioneOliveira/Kafka-detectar-fraude.git
cd Kafka-detectar-fraude

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 15.2 Recriar os arquivos locais

Como o armazenamento do terminal expirou, gere novamente o dataset e o
modelo:

```bash
python treinar_fraude.py
```

Crie o `config.env`:

```bash
nano config.env
```

Recupere no Portal Azure as connection strings do namespace Event Hubs e da
Storage Account já existentes. Preencha:

```text
EVENTHUB_NAMESPACE=nome-do-namespace
EVENTHUB_CONNECTION=Endpoint=sb://...
STORAGE_CONNECTION=DefaultEndpointsProtocol=https;...
API_URL=http://ENDERECO_PUBLICO_DA_API:8000
```

Para descobrir o endereço do ACI pelo Cloud Shell:

```bash
az container show \
  --resource-group fraude-rg \
  --name fraude-api \
  --query "{estado:instanceView.state,ip:ipAddress.ip,fqdn:ipAddress.fqdn}" \
  --output table
```

Substitua `API_URL` pelo IP ou FQDN retornado e teste a API:

```bash
curl "$API_URL/health"
```

### 15.3 Iniciar o processamento

Abra uma segunda aba do Cloud Shell, repita `cd Kafka-detectar-fraude` e
ative o ambiente virtual. Na primeira aba, inicie o consumidor com um grupo
novo para reprocessar as mensagens desde o começo:

```bash
python consumidor.py \
  --grupo "fraude-retomada-$(date +%s)" \
  --api \
  --blob \
  --desde-o-inicio \
  --prefixo retomada
```

Na segunda aba, ative o ambiente virtual e publique as transações:

```bash
python produtor.py --arquivo fraud.csv --quantidade 100
```

Os resultados serão gravados no container `avaliacoes`, separados em
`retomada/fraude/` e `retomada/normal/`. Não feche a aba do consumidor
enquanto o produtor estiver enviando mensagens.

## 16. Limpar os recursos e evitar custos

Quando terminar a prática, no Portal:

1. Pesquise **Resource groups**.
2. Abra `fraude-rg`.
3. Clique em **Delete resource group**.
4. Digite o nome do Resource Group para confirmar.
5. Clique em **Delete**.

Isso remove a Storage Account, o Event Hubs e o Container Instance criados
neste tutorial.

Também é possível usar o Cloud Shell:

```bash
az group delete \
  --name fraude-rg \
  --yes \
  --no-wait
```

## 17. Problemas comuns

| Problema | Correção |
|---|---|
| `bash: --name: command not found` | O comando está usando crase do PowerShell. No Bash, use `\` no fim de cada linha. |
| O download do dataset falha | Verifique a conexão e execute novamente `python treinar_fraude.py`. |
| O Event Hubs recusa a conexão Kafka | Confirme que o namespace usa o tier **Standard**, não **Basic**. |
| O tópico `fraudes` não foi encontrado | Confirme que o Event Hub foi criado com esse nome no namespace correto. |
| A API não responde | Confira o IP, a porta TCP 8000, o estado `Running` do ACI e os logs do container. |
| `STORAGE_CONNECTION` é rejeitada | Copie novamente a connection string em **Storage Account > Security + networking > Access keys**. |
| O container `avaliacoes` não existe | Crie-o em **Storage Account > Data storage > Containers** com acesso privado. |
| O consumidor não recebe mensagens | Use um grupo novo ou acrescente `--desde-o-inicio` na primeira execução. |
| `dockerDesktopLinuxEngine` não é encontrado no Windows | Abra o Docker Desktop, aguarde **Engine running** e confirme que o modo **Linux containers** está ativo com `docker version`. |
| O modelo não foi encontrado na imagem | Execute `python treinar_fraude.py` antes de `docker build`. |
| O GitHub rejeita o dataset | Não faça `git add fraud.csv`; o arquivo já está no `.gitignore`. |
