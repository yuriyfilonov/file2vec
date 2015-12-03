package extraction

class DotSlidingWindow(tokenizer: Tokenizer) extends SlidingWindow(tokenizer) {
  val sentenceSeparator = "\\.".r

  def sentences(text: String): Array[String] = {
    sentenceSeparator.split(text)
  }
}
