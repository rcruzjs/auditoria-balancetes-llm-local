-- Dados iniciais: categorias e regras (foco em consumo e serviços de eventos).
-- As categorias e regras podem ser editadas e ampliadas depois. As contas bancárias são criadas pela
-- carga a partir dos extratos; apelidos podem ser dados depois com UPDATE contas_bancarias SET apelido = ...

INSERT INTO categorias (nome, grupo, descricao, cor) VALUES
  -- Eventos (foco da análise)
  ('Buffet',                        'Eventos', 'Buffet, salgados, doces, bolos, catering', '#E07A5F'),
  ('Bebidas',                       'Eventos', 'Bebidas, distribuidoras, chopp, gelo', '#F2CC8F'),
  ('Restaurante e alimentação',     'Eventos', 'Restaurante, lanchonete, alimentação', '#81B29A'),
  ('Promotores e produção',         'Eventos', 'Promoters, produtoras, cerimonial, assessoria de eventos', '#3D405B'),
  ('Shows e artistas',              'Eventos', 'Bandas, músicos, DJs, cachês artísticos', '#9B5DE5'),
  ('Som, luz e estrutura',          'Eventos', 'Som, iluminação, palco, tendas, geradores, locação de equipamentos', '#00BBF9'),
  ('Decoração',                     'Eventos', 'Decoração, flores, balões, ambientação', '#F15BB5'),
  ('Recreação e animação',          'Eventos', 'Recreadores, brinquedos, animação infantil', '#FEE440'),
  ('Eventos esportivos',            'Eventos', 'Arbitragem, ligas, federações, troféus, medalhas, inscrições', '#00F5D4'),
  ('Segurança e apoio de eventos',  'Eventos', 'Segurança, brigada, limpeza e apoio contratados para eventos', '#8D99AE'),
  ('Cultural',                      'Eventos', 'Teatro, exposições, oficinas culturais', '#6D597A'),
  -- Demais despesas
  ('Pessoal',                       'Pessoal', 'Salários, encargos, benefícios, rescisões', '#6C757D'),
  ('Utilidades',                    'Operacional', 'Energia, água, gás, telefone, internet', '#ADB5BD'),
  ('Manutenção e obras',            'Operacional', 'Manutenção predial, piscina, materiais, obras', '#ADB5BD'),
  ('Serviços profissionais',        'Operacional', 'Contabilidade, advocacia, auditoria, TI', '#ADB5BD'),
  ('Tributos',                      'Operacional', 'Impostos, taxas, guias', '#ADB5BD'),
  ('Tarifas bancárias',             'Operacional', 'Tarifas e encargos do banco', '#ADB5BD'),
  ('Outras despesas',               'Operacional', 'Não classificadas', '#DEE2E6'),
  -- Receitas
  ('Mensalidades e associados',     'Receitas', 'Manutenção mensal, cobranças, PIX de sócios', '#2A9D8F'),
  ('Cartões',                       'Receitas', 'Vendas e antecipações de cartão', '#2A9D8F'),
  ('Outras receitas',               'Receitas', 'Aluguéis, patrocínios, taxas', '#2A9D8F');

-- Regras iniciais por palavra-chave (aplicadas ao nome da contraparte e à descrição, sem acento)
INSERT INTO regras_categoria (padrao, categoria_id, prioridade)
SELECT p, (SELECT id FROM categorias WHERE nome = c), pr FROM (VALUES
  ('BUFFET|BUFET|SALGAD|DOCES|CONFEIT|BOLOS|CATERING',                'Buffet', 10),
  ('BEBIDA|DISTRIB|CHOPP|CHOP |CERVEJ|AMBEV|HEINEKEN|GELO|REFRIG',   'Bebidas', 10),
  ('RESTAURANTE|LANCHONETE|PIZZ|CHURRASC|ALIMENTAC|HORTIFRUT',       'Restaurante e alimentação', 20),
  ('PRODUC|PRODUTORA|EVENTOS|CERIMONIAL|PROMO',                      'Promotores e produção', 30),
  ('BANDA|MUSIC|MUSICA|DJ |SHOW|ARTISTIC',                           'Shows e artistas', 30),
  ('SONORIZ|ILUMINAC|PALCO|TENDA|GERADOR|LOCACAO DE EQUIP',          'Som, luz e estrutura', 30),
  ('DECORAC|FLORES|FLORICULT|BALOES',                                'Decoração', 30),
  ('RECREAC|RECREADOR|BRINQUED|ANIMAC',                              'Recreação e animação', 30),
  ('LIGA |FEDERAC|ARBITR|TROFEU|MEDALHA|CONFEDERAC',                 'Eventos esportivos', 30),
  ('PAGAMENTO DE SALARIO|PAGSAL|FOPA|FGTS|INSS|RESCIS',              'Pessoal', 10),
  ('AMPLA|ENEL|ENERGIA|AGUAS DE |CEDAE|SUPERGASBRAS|GAS |CLARO|VIVO|TIM |OI S',  'Utilidades', 20),
  ('CONTABIL|ADVOGAD|ADVOCACIA|AUDITORIA|SUPORTE TECNOLOGIA|INFORMATICA|SISTEMAS',     'Serviços profissionais', 40),
  ('TRIBUTO|DARF|DAS |GPS|IPTU|PREFEITURA',               'Tributos', 20),
  ('^TAR |TARIFA|IOF|ENCARGO',                                       'Tarifas bancárias', 10),
  ('QUIMIC|PISCINA|MATERIA|CONSTRU|FERRAGEM|ELETRIC|HIDRAUL|MANUTENC|REFORMA',          'Manutenção e obras', 50),
  ('CR COB|COBRANCA',                                                'Mensalidades e associados', 20),
  ('STONE|CIELO|GETNET|REDE |ANTECIPACAO CREDENCIADORA|CARTAO',      'Cartões', 20)
) AS r(p, c, pr);
