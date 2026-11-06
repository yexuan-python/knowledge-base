from knowledge_base.brand import full_markdown


def test_render_inline_markdown_keeps_literal_asterisks_in_dimension_tokens() -> None:
    rendered = full_markdown._render_inline_markdown("尺寸:1000*1855*785mm")

    assert rendered == "尺寸:1000*1855*785mm"


def test_render_inline_markdown_still_supports_emphasis() -> None:
    rendered = full_markdown._render_inline_markdown("这是*重点*内容")

    assert rendered == "这是<em>重点</em>内容"


def test_markdown_to_html_blocks_keeps_dimension_text_in_list_items() -> None:
    rendered = full_markdown._markdown_to_html_blocks("- 尺寸:1000*1855*785mm")

    assert "<li>尺寸:1000*1855*785mm</li>" in rendered


def test_render_inline_markdown_normalizes_square_meter_units_for_pdf_display() -> None:
    rendered = full_markdown._render_inline_markdown("金牌实木多层板新品 899元/m2，套餐含20m2定制衣柜")

    assert rendered == "金牌实木多层板新品 899元/㎡，套餐含20m²定制衣柜"


def test_render_inline_markdown_normalizes_cubic_meter_units_for_pdf_display() -> None:
    rendered = full_markdown._render_inline_markdown("甲醛释放量≤0.025mg/m3")

    assert rendered == "甲醛释放量≤0.025mg/m³"


def test_render_inline_markdown_normalizes_common_square_and_cubic_units_for_pdf_display() -> None:
    rendered = full_markdown._render_inline_markdown(
        "体积15cm3，面积30cm2，厚度区域2mm2，单m2价格899元，每m2补差价10元"
    )

    assert rendered == "体积15cm³，面积30cm²，厚度区域2mm²，单㎡价格899元，每㎡补差价10元"


def test_render_inline_markdown_does_not_touch_model_like_tokens() -> None:
    rendered = full_markdown._render_inline_markdown("型号X3m2 不是单位，版本Team2 不应变化")

    assert rendered == "型号X3m2 不是单位，版本Team2 不应变化"


def test_render_inline_markdown_normalizes_formula_denominator_exponents() -> None:
    rendered = full_markdown._render_inline_markdown("加速度9.8m/s2，角加速度1rad/s^2，日衰减率按1/h2估算")

    assert rendered == "加速度9.8m/s²，角加速度1rad/s²，日衰减率按1/h²估算"


def test_render_inline_markdown_normalizes_common_chemical_formulas() -> None:
    rendered = full_markdown._render_inline_markdown("CO2、H2O、Fe2O3、Mg(OH)2、CuSO4·5H2O、NH4+、SO4^2-")

    assert rendered == "CO₂、H₂O、Fe₂O₃、Mg(OH)₂、CuSO₄·5H₂O、NH₄⁺、SO₄²⁻"


def test_render_inline_markdown_does_not_touch_version_like_formula_tokens() -> None:
    rendered = full_markdown._render_inline_markdown("版本V2 保持不变，Team2 保持不变，型号X3m2 保持不变")

    assert rendered == "版本V2 保持不变，Team2 保持不变，型号X3m2 保持不变"


def test_render_inline_markdown_does_not_touch_standard_or_model_tokens() -> None:
    rendered = full_markdown._render_inline_markdown("通过ISO9001认证，并发布新品 JL60A 黑咖专用机型")

    assert rendered == "通过ISO9001认证，并发布新品 JL60A 黑咖专用机型"
