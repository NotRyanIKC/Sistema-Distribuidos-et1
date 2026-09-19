#!/bin/bash
# ==============================================================================
# provisionar_aws.sh
# ==============================================================================
# Provisiona a instância EC2 do projeto (Etapa 1, Sistemas Distribuídos).
# Idempotente: rodar de novo reaproveita chave, grupo de segurança e instância.
#
# Grupo de segurança:
#   22/tcp   (SSH, porta ADMINISTRATIVA)  origem: IP público da equipe /32
#   8000/tcp (servidor_status.py, porta do SERVIÇO)  origem: ORIGEM_SERVICO
#   Nenhuma regra de entrada para 0.0.0.0/0 na porta 22: o script aborta se isso acontecer.
#
# Pré-requisitos: AWS CLI v2 configurado (aws configure, ou credenciais do lab
# coladas em ~/.aws/credentials).
#
# Uso:
#   ./provisionar_aws.sh
#   EXTRA_CIDRS="200.10.20.30/32" ./provisionar_aws.sh        # IP da sala, de outro integrante...
#   TIPO_INSTANCIA=c7a.xlarge AZ=us-east-1b ./provisionar_aws.sh
# ==============================================================================

set -euo pipefail

# ── Configurações (podem ser sobrescritas por variável de ambiente) ──────────
REGIAO="${REGIAO:-us-east-1}"
AZ="${AZ:-us-east-1a}"
TIPO_INSTANCIA="${TIPO_INSTANCIA:-c6i.xlarge}"   # 4 vCPUs (2 núcleos físicos x 2 threads), 8 GiB
VOLUME_GB="${VOLUME_GB:-50}"
IOPS="${IOPS:-3000}"
THROUGHPUT="${THROUGHPUT:-125}"                   # MB/s (base do gp3, sem custo extra)
NOME_SG="${NOME_SG:-sg-benchmark-etapa1}"
NOME_KEY="${NOME_KEY:-kp-benchmark-etapa1}"
NOME_INSTANCIA="${NOME_INSTANCIA:-ec2-benchmark-etapa1}"
PORTA_ADMIN=22
PORTA_SERVICO=8000

MY_IP="$(curl -s https://checkip.amazonaws.com | tr -d '[:space:]')/32"
EXTRA_CIDRS="${EXTRA_CIDRS:-}"                    # outros /32 da equipe, separados por espaço
ORIGEM_SERVICO="${ORIGEM_SERVICO:-$MY_IP}"        # quem pode acessar a porta do serviço

if [[ ! "$MY_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/32$ ]]; then
    echo "[ERRO] Não foi possível detectar o IP público (obtido: '$MY_IP')."; exit 1
fi
for c in $MY_IP $EXTRA_CIDRS; do
    if [[ "$c" == "0.0.0.0/0" ]]; then
        echo "[ERRO] A porta administrativa nunca pode ser aberta para 0.0.0.0/0."; exit 1
    fi
done
echo "[INFO] Região $REGIAO | AZ $AZ | tipo $TIPO_INSTANCIA"
echo "[INFO] Origem da porta $PORTA_ADMIN: $MY_IP $EXTRA_CIDRS"
echo "[INFO] Origem da porta $PORTA_SERVICO: $ORIGEM_SERVICO"

# ── 1. Par de chaves ──────────────────────────────────────────────────────────
echo "[1/6] Par de chaves: $NOME_KEY"
if aws ec2 describe-key-pairs --key-names "$NOME_KEY" --region "$REGIAO" &>/dev/null; then
    echo "  Já existe."
    [[ -f "${NOME_KEY}.pem" ]] || echo "  [AVISO] ${NOME_KEY}.pem não está nesta pasta. Use a cópia de quem criou a chave."
else
    aws ec2 create-key-pair --key-name "$NOME_KEY" --query "KeyMaterial" --output text \
        --region "$REGIAO" > "${NOME_KEY}.pem"
    chmod 400 "${NOME_KEY}.pem"
    echo "  Chave salva em ${NOME_KEY}.pem (não versionar no Git)"
fi

# ── 2. AMI mais recente do Amazon Linux 2023 ─────────────────────────────────
echo "[2/6] Buscando AMI Amazon Linux 2023 (x86_64)"
AMI_ID=$(aws ec2 describe-images --owners amazon --region "$REGIAO" \
    --filters "Name=name,Values=al2023-ami-2023.*-x86_64" "Name=state,Values=available" \
    --query "sort_by(Images, &CreationDate)[-1].ImageId" --output text)
echo "  AMI: $AMI_ID"

# ── 3. Grupo de segurança ─────────────────────────────────────────────────────
echo "[3/6] Grupo de segurança: $NOME_SG"
SG_ID=$(aws ec2 describe-security-groups --region "$REGIAO" \
    --filters "Name=group-name,Values=$NOME_SG" --query "SecurityGroups[0].GroupId" --output text)
if [[ "$SG_ID" == "None" || -z "$SG_ID" ]]; then
    SG_ID=$(aws ec2 create-security-group --group-name "$NOME_SG" --region "$REGIAO" \
        --description "Etapa 1: SSH so da equipe, 8000 servico de status" \
        --query "GroupId" --output text)
    echo "  Criado: $SG_ID"
else
    echo "  Já existe: $SG_ID"
fi

liberar() {  # porta cidr descricao
    aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --region "$REGIAO" \
        --ip-permissions "IpProtocol=tcp,FromPort=$1,ToPort=$1,IpRanges=[{CidrIp=$2,Description=\"$3\"}]" \
        &>/dev/null && echo "  + $1/tcp <- $2 ($3)" || echo "  = $1/tcp <- $2 (já existia)"
}
for c in $MY_IP $EXTRA_CIDRS; do liberar $PORTA_ADMIN "$c" "SSH equipe"; done
liberar $PORTA_SERVICO "$ORIGEM_SERVICO" "servidor_status.py"

# Garantia: nenhuma regra que cubra a porta administrativa aceita 0.0.0.0/0 ou ::/0
ABERTA=$(aws ec2 describe-security-groups --group-ids "$SG_ID" --region "$REGIAO" --output text \
    --query "SecurityGroups[0].IpPermissions[?IpProtocol=='-1' || (FromPort<=\`$PORTA_ADMIN\` && ToPort>=\`$PORTA_ADMIN\`)].[IpRanges[?CidrIp=='0.0.0.0/0'].CidrIp, Ipv6Ranges[?CidrIpv6=='::/0'].CidrIpv6][][]")
if [[ -n "$ABERTA" ]]; then
    echo "[ERRO] O SG $SG_ID tem regra que abre a porta $PORTA_ADMIN para qualquer origem ($ABERTA)."
    echo "       Remova essa regra no console antes de continuar."
    exit 1
fi
echo "  Verificado: porta $PORTA_ADMIN não está aberta para qualquer origem."

# ── 4. Instância (reaproveita se já existir) ─────────────────────────────────
echo "[4/6] Instância $NOME_INSTANCIA"
INSTANCE_ID=$(aws ec2 describe-instances --region "$REGIAO" \
    --filters "Name=tag:Name,Values=$NOME_INSTANCIA" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query "Reservations[0].Instances[0].InstanceId" --output text)
if [[ "$INSTANCE_ID" == "None" || -z "$INSTANCE_ID" ]]; then
    INSTANCE_ID=$(aws ec2 run-instances --region "$REGIAO" \
        --image-id "$AMI_ID" \
        --instance-type "$TIPO_INSTANCIA" \
        --key-name "$NOME_KEY" \
        --security-group-ids "$SG_ID" \
        --placement "AvailabilityZone=$AZ" \
        --block-device-mappings "[{\"DeviceName\":\"/dev/xvda\",\"Ebs\":{\"VolumeSize\":$VOLUME_GB,\"VolumeType\":\"gp3\",\"Iops\":$IOPS,\"Throughput\":$THROUGHPUT,\"DeleteOnTermination\":true}}]" \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NOME_INSTANCIA}]" \
        --query "Instances[0].InstanceId" --output text)
    echo "  Criada: $INSTANCE_ID"
else
    echo "  Já existe: $INSTANCE_ID (iniciando se estiver parada)"
    aws ec2 start-instances --instance-ids "$INSTANCE_ID" --region "$REGIAO" &>/dev/null || true
fi

# ── 5. Aguardar ──────────────────────────────────────────────────────────────
echo "[5/6] Aguardando estado 'running'..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$REGIAO"
PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGIAO" \
    --query "Reservations[0].Instances[0].PublicIpAddress" --output text)

# ── 6. Registro ──────────────────────────────────────────────────────────────
echo "[6/6] Salvando instancia_info.txt"
cat > instancia_info.txt << EOF
INSTANCE_ID=$INSTANCE_ID
PUBLIC_IP=$PUBLIC_IP
SG_ID=$SG_ID
REGIAO=$REGIAO
AZ=$AZ
TIPO=$TIPO_INSTANCIA
AMI=$AMI_ID
KEY_FILE=${NOME_KEY}.pem
EOF

echo ""
echo "============================================================"
echo "INSTÂNCIA PRONTA"
echo "  ID         : $INSTANCE_ID"
echo "  IP público : $PUBLIC_IP"
echo "  Região/AZ  : $REGIAO / $AZ"
echo "  Tipo       : $TIPO_INSTANCIA"
echo "  SG         : $SG_ID"
echo ""
echo "Próximos passos:"
echo "  scp -i ${NOME_KEY}.pem *.py *.sh ec2-user@$PUBLIC_IP:~/benchmark/   (crie a pasta antes: ssh ... mkdir -p benchmark)"
echo "  ssh -i ${NOME_KEY}.pem ec2-user@$PUBLIC_IP"
echo ""
echo "Conferir recursos e regras: ./mostrar_recursos.sh"
echo "Encerrar ao final        : aws ec2 terminate-instances --instance-ids $INSTANCE_ID --region $REGIAO"
echo "============================================================"
