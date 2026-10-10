-- Ajustes após a 1ª conferência das regras (out/2026):
-- ENEL caía em Bebidas ("DISTRIBUICAO"), refrigeração (ar-condicionado) em Bebidas,
-- e "Cacau Show" / "Show Room" em Shows.
UPDATE regras_categoria SET padrao = 'BEBIDA|DISTRIBUI|CHOPP|CHOP |CERVEJ|AMBEV|HEINEKEN|GELO ' 
 WHERE categoria_id = (SELECT id FROM categorias WHERE nome = 'Bebidas');
UPDATE regras_categoria SET padrao = 'BANDA|MUSIC|DJ |ARTISTIC|CACHE ' 
 WHERE categoria_id = (SELECT id FROM categorias WHERE nome = 'Shows e artistas');
UPDATE regras_categoria SET prioridade = 5, padrao = 'AMPLA|ENEL|ENERGIA|AGUAS DE |AGUA E ESGOTO|CEDAE|SUPERGASBRAS|GAS |CLARO|VIVO|TIM |OI S|DEAL COMERCIALIZADORA'
 WHERE categoria_id = (SELECT id FROM categorias WHERE nome = 'Utilidades');
INSERT INTO regras_categoria (padrao, categoria_id, prioridade)
SELECT 'REFRIGERAC|AR CONDICIONADO|PRESSURIZAC', id, 5 FROM categorias WHERE nome = 'Manutenção e obras';
INSERT INTO regras_categoria (padrao, categoria_id, prioridade)
SELECT 'CACAU SHOW|SHOWCOLATE|CHOCOLATE', id, 8 FROM categorias WHERE nome = 'Restaurante e alimentação';
